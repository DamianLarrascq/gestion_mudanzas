from __future__ import annotations
import json
import logging

from dateutil.tz import tzname_in_python2
from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db import transaction
from django.contrib.auth.models import User

from gestion.models import Cliente
from gestion.models.mudanzas import Mudanza
from gestion.models.auditoria import HistorialEstado
from gestion.models.chatbot import SesionChatbot
from gestion.services.chatbot_service import ResultadoChatbot, ChatbotHandler
from twilio.rest import Client
from twilio.request_validator import RequestValidator
import re

logger = logging.getLogger(__name__)
_LOG_SANITIZE_RE = re.compile(r"[\r\n\x00-\x1f\x7f]")
_LOG_MAX_LEN = 200

# Usuario de sistema para registrar cambios de estado automáticos en HistorialEstado.
# Debe existir en la DB. Crearlo con:
#   python manage.py shell -c "from django.contrib.auth.models import User; User.objects.get_or_create(username='sistema', defaults={'is_active': False})"
_SISTEMA_USERNAME = "sistema"


def _sanitize_log(value: object, max_len: int = _LOG_MAX_LEN) -> str:
    """
    Elimina caracteres de control de valores externos antes de loguearlos.
    Previene log injection (CWE-177).
    """
    s = str(value)
    s = _LOG_SANITIZE_RE.sub('', s)
    return s[:max_len] if len(s) > max_len else s


def _get_usuario_sistema() -> User:
    user, _ = User.objects.get_or_create(
        username=_SISTEMA_USERNAME,
        defaults={'is_active': False}
    )
    return user


@csrf_exempt
@require_POST
def mp_notificacion(request):
    """
    POST /webhook/mp/notificacion/

    MercadoPago envía notificaciones de pago aquí (IPN / Webhooks).
    Documentación: https://www.mercadopago.com.ar/developers/es/docs/your-integrations/notifications

    Flujo:
        1. Parsear el body JSON de MP
        2. Ignorar notificaciones que no sean de tipo "payment"
        3. Consultar el estado del pago en la API de MP
        4. Si status == "approved": buscar la Mudanza por uuid y confirmarla
        5. Retornar HTTP 200 siempre (MP reintenta si recibe != 200)

    Nota de seguridad: validar la firma X-Signature de MP antes de procesar
    en producción. Ver: https://www.mercadopago.com.ar/developers/es/docs/your-integrations/notifications/webhooks#editor_14
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        logger.warning("webhook/mp: body inválido recibido")
        return HttpResponse(status=200)  # igual 200 para que MP no reintente

    tipo = body.get("type")
    datos = body.get("data", {})

    if tipo != "payment":
        # MP también envía notificaciones de "merchant_order", etc. Ignorar.
        return HttpResponse(status=200)

    payment_id = datos.get("id")
    if not payment_id:
        logger.warning("webhook/mp: notificación de pago sin id")
        return HttpResponse(status=200)

    try:
        _procesar_pago(payment_id)
    except Exception as exc:
        # Loguear pero retornar 200 igual: no queremos reintentos infinitos
        # de MP por errores internos. El estado queda en PRESUPUESTADA y
        # el admin puede resolver manualmente.
        logger.exception("webhook/mp: error procesando payment_id=%s — %s", _sanitize_log(payment_id), exc)

    return HttpResponse(status=200)


def _procesar_pago(payment_id: str | int) -> None:
    """
    Consulta el pago en MP y, si está aprobado, confirma la Mudanza.
    """
    from gestion.services.mercadopago_service import _get_sdk

    sdk = _get_sdk()
    response = sdk.payment().get(payment_id)

    if response["status"] != 200:
        logger.error("webhook/mp: no se pudo obtener payment_id=%s, status=%s", _sanitize_log(payment_id),
                     response["status"])
        return

    pago = response["response"]
    estado_pago = pago.get("status")
    metadata = pago.get("metadata", {})
    mudanza_uuid = metadata.get("mudanza_uuid") or pago.get('external_reference')

    if estado_pago != "approved":
        logger.info("webhook/mp: payment_id=%s estado=%s — ignorado", _sanitize_log(payment_id), _sanitize_log(estado_pago))
        return

    if not mudanza_uuid:
        logger.error("webhook/mp: payment_id=%s aprobado pero sin mudanza_uuid en metadata", _sanitize_log(payment_id))
        return

    _confirmar_mudanza(mudanza_uuid)


def _confirmar_mudanza(mudanza_uuid: str) -> None:
    """
    Transiciona la Mudanza de PRESUPUESTADA → CONFIRMADA y registra el historial.
    Idempotente: si ya está CONFIRMADA no hace nada.
    """
    try:
        mudanza = Mudanza.objects.select_related('cliente').get(uuid=mudanza_uuid)
    except Mudanza.DoesNotExist:
        logger.error("webhook/mp: Mudanza uuid=%s no encontrada", _sanitize_log(mudanza_uuid))
        return

    if mudanza.estado == Mudanza.Estado.CONFIRMADA:
        logger.info("webhook/mp: Mudanza uuid=%s ya estaba CONFIRMADA — sin cambios", _sanitize_log(mudanza_uuid))
        return

    if mudanza.estado != Mudanza.Estado.PRESUPUESTADA:
        logger.warning(
            "webhook/mp: Mudanza uuid=%s está en estado=%s, se esperaba PRESUPUESTADA — igual se confirma",
            _sanitize_log(mudanza_uuid),
            mudanza.estado,
        )

    estado_anterior = mudanza.estado
    usuario_sistema = _get_usuario_sistema()

    with transaction.atomic():
        Mudanza.objects.filter(pk=mudanza.pk).update(
            estado=Mudanza.Estado.CONFIRMADA,
            senia_pagada=True,
        )
        HistorialEstado.objects.create(
            mudanza=mudanza,
            estado_anterior=estado_anterior,
            estado_nuevo=Mudanza.Estado.CONFIRMADA,
            usuario=usuario_sistema,
        )

    logger.info("webhook/mp: Mudanza #%s uuid=%s confirmada correctamente", mudanza.pk, mudanza_uuid)

    _notificar_confirmacion_pago(mudanza)

def _notificar_confirmacion_pago(mudanza: Mudanza) -> None:
    """
    Envia la confirmacion de pago por Whatsapp y la audita en Notificacion.
    No debe interrumpir el flujo del webhook si falla - el estado ya quedo confirmado.
    """
    from gestion.services.chatbot_service import construir_mensaje_confirmacion_pago
    from gestion.models.notificaciones import Notificacion

    mensajes = construir_mensaje_confirmacion_pago(
        cliente_nombre=mudanza.cliente.nombre_completo,
        mudanza_origen=mudanza.origen,
        mudanza_destino=mudanza.destino
    )

    for mensaje in mensajes:
        _enviar_mensaje_whatsapp(mudanza.cliente.telefono, mensaje)

        try:
            Notificacion.objects.create(
                mudanza=mudanza,
                tipo=Notificacion.Tipo.CONFIRMACION,
                canal=Notificacion.Canal.WHATSAPP,
                destinatario=mudanza.cliente.telefono,
                enviada=True,
                enviada_en=timezone.now(),
                error="",
            )
        except Exception:
            logger.exception(
                "No se pudo registrar Notificacion de confirmacion para Mudanza #%s", mudanza.pk
            )

# ── Páginas de retorno de MercadoPago ─────────────────────────────────────────
# MP redirige al usuario a estas URLs desde el browser.
# No son webhooks — son vistas normales que el usuario ve.

def mp_success(request):
    """GET /webhook/mp/success/ — redirige a la página de gracias."""
    from django.shortcuts import redirect
    return redirect("public:presupuesto_gracias")


def mp_failure(request):
    from django.shortcuts import render
    return render(request, "public/pago_fallido.html", {
        "payment_id": request.GET.get("payment_id"),
        "status": request.GET.get("status"),
    })


def mp_pending(request):
    from django.shortcuts import render
    return render(request, "public/pago_pendiente.html", {
        "payment_id": request.GET.get("payment_id"),
        "status": request.GET.get("status"),
    })


# ── Cliente Twilio ────────────────────────────────────────────────────────

def _get_twilio_client() -> Client:
    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


# ── Envío de mensajes ─────────────────────────────────────────────────────

def _normalizar_telefono_ar_whatsapp(telefono: str) -> str:
    """
    Normaliza un telefono argentino al formato E.164 que exige WhatsApp: +549<area><numero>

    Asume que telefono llega sin 0 ni 15 (convencion de los formularios del sistema,
    ej: "1123456789" para Bs. As.) Si ya viene con "+" o con codigo de pais, lo respeta.
    No resuelve numero con 0/15 sin stripear - ese caso no se da en los formularios actuales.
    """

    crudo = telefono.strip()
    if crudo.startswith("+"):
        return crudo

    solo_digitos = re.sub(r"\D", "", crudo)
    if solo_digitos.startswith("549"):
        return f"+{solo_digitos}"
    if solo_digitos.startswith("54"):
        return f"+549{solo_digitos[2:]}"
    return f"+549{solo_digitos}"

def _enviar_mensaje_whatsapp(telefono: str, texto: str) -> None:
    """
    Envía un mensaje de texto vía Twilio WhatsApp.

    Args:
        telefono: Numero destino. Si ya trae el prefijo "whatsapp:" se respeta tal cual
                (caso de respuestas al chatbot, donde ya llega en E.164 desde Twilio).
                Si no, se normaliza a formato argentino antes de enviar.

        texto: Cuerpo del mensaje.
    """
    if getattr(settings, "TWILIO_SANDBOX", True):
        logger.info("[TWILIO SANDBOX] → %s: %s", telefono, texto)
        return

    # Normalizar: Twilio requiere el prefijo "whatsapp:"
    if telefono.startswith("whatsapp:"):
        destino = telefono
    else:
        destino = f"whatsapp:{_normalizar_telefono_ar_whatsapp(telefono)}"

    try:
        client = _get_twilio_client()
        message = client.messages.create(
            from_=settings.TWILIO_WHATSAPP_FROM,
            to=destino,
            body=texto,
        )
        logger.info("Mensaje enviado vía Twilio. SID: %s", message.sid)
    except Exception:
        logger.exception("Error enviando mensaje Twilio a %s.", destino)


def _enviar_respuestas(telefono: str, resultado: ResultadoChatbot) -> None:
    """Despacha cada mensaje del resultado de forma secuencial."""
    for mensaje in resultado.mensajes:
        _enviar_mensaje_whatsapp(telefono, mensaje)


# ── Validación de firma de Twilio ─────────────────────────────────────────

def _verificar_firma_twilio(request: HttpRequest) -> bool:
    """
    Valida que el request provenga realmente de Twilio usando RequestValidator.

    Twilio firma con HMAC-SHA1 sobre: URL completa + parámetros POST ordenados.
    Docs: https://www.twilio.com/docs/usage/webhooks/webhooks-security

    En modo SANDBOX (desarrollo local) se omite la validación para facilitar
    pruebas con ngrok u otras herramientas de túnel.
    """
    if getattr(settings, "TWILIO_SANDBOX", True):
        logger.debug("Validación de firma Twilio omitida (modo SANDBOX).")
        return True

    firma = request.META.get("HTTP_X_TWILIO_SIGNATURE", "")
    if not firma:
        logger.warning("Request sin cabecera X-Twilio-Signature.")
        return False

    # La URL debe ser exactamente la misma que Twilio tiene configurada en su console.
    url = f"{settings.SITE_BASE_URL.rstrip('/')}/webhook/whatsapp/"

    validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
    return validator.validate(url, request.POST, firma)


# ── Vista principal ───────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name="dispatch")
class WhatsAppWebhookView(View):
    """
    POST /webhook/whatsapp/

    Twilio no hace un handshake GET de verificación (a diferencia de Meta),
    por lo que solo implementamos POST.

    Payload relevante de Twilio (form-data):
        From:    "whatsapp:+5491123456789"
        Body:    "Hola, quiero pedir un presupuesto para una mudanza."
        NumMedia: "0"   (si hay adjuntos, > 0)
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        if not _verificar_firma_twilio(request):
            logger.warning("Firma Twilio inválida. Request rechazado.")
            return HttpResponse("Forbidden", status=403)

        telefono_raw = request.POST.get("From", "")
        texto = request.POST.get("Body", "").strip()
        num_media = int(request.POST.get("NumMedia", "0"))

        if not telefono_raw:
            logger.warning("Webhook de Twilio sin campo 'From'.")
            return HttpResponse(status=400)

        # Normalizar: quitar el prefijo "whatsapp:" para usar como canal_id
        # Se vuelve a agregar al enviar con _enviar_mensaje_whatsapp.
        canal_id = (
            telefono_raw.removeprefix("whatsapp:")
            if telefono_raw.startswith("whatsapp:")
            else telefono_raw
        )

        if num_media > 0:
            # Mensajes con adjuntos (imágenes, audio, documentos): ignorar por ahora.
            logger.info("Mensaje con media ignorado (de: %s).", canal_id)
            return HttpResponse(status=200)

        if not texto:
            return HttpResponse(status=200)

        logger.info("Mensaje WA recibido de %s: %s", canal_id, texto[:80])

        resultado = ChatbotHandler.procesar(
            canal_id=canal_id,
            canal=SesionChatbot.Canal.WHATSAPP,
            texto=texto,
        )

        _enviar_respuestas(canal_id, resultado)

        # 200 vacío: Twilio no necesita TwiML cuando respondemos vía REST API.
        return HttpResponse(status=200)
