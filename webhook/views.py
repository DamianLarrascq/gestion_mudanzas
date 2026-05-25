from __future__ import annotations
import json
import logging
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db import transaction
from django.contrib.auth.models import User
from gestion.models.mudanzas import Mudanza
from gestion.models.auditoria import HistorialEstado

logger = logging.getLogger(__name__)

# Usuario de sistema para registrar cambios de estado automáticos en HistorialEstado.
# Debe existir en la DB. Crearlo con:
#   python manage.py shell -c "from django.contrib.auth.models import User; User.objects.get_or_create(username='sistema', defaults={'is_active': False})"
_SISTEMA_USERNAME = "sistema"


def _get_usuario_sistema() -> User:
    return User.objects.get(username=_SISTEMA_USERNAME)


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
        logger.exception("webhook/mp: error procesando payment_id=%s — %s", payment_id, exc)

    return HttpResponse(status=200)


def _procesar_pago(payment_id: str | int) -> None:
    """
    Consulta el pago en MP y, si está aprobado, confirma la Mudanza.
    """
    from gestion.services.mercadopago_service import _get_sdk
    from django.conf import settings

    sdk = _get_sdk()
    response = sdk.payment().get(payment_id)

    if response["status"] != 200:
        logger.error("webhook/mp: no se pudo obtener payment_id=%s, status=%s", payment_id, response["status"])
        return

    pago = response["response"]
    estado_pago = pago.get("status")
    metadata = pago.get("metadata", {})
    mudanza_uuid = metadata.get("mudanza_uuid")

    if estado_pago != "approved":
        logger.info("webhook/mp: payment_id=%s estado=%s — ignorado", payment_id, estado_pago)
        return

    if not mudanza_uuid:
        logger.error("webhook/mp: payment_id=%s aprobado pero sin mudanza_uuid en metadata", payment_id)
        return

    _confirmar_mudanza(mudanza_uuid)


def _confirmar_mudanza(mudanza_uuid: str) -> None:
    """
    Transiciona la Mudanza de PRESUPUESTADA → CONFIRMADA y registra el historial.
    Idempotente: si ya está CONFIRMADA no hace nada.
    """
    try:
        mudanza = Mudanza.objects.get(uuid=mudanza_uuid)
    except Mudanza.DoesNotExist:
        logger.error("webhook/mp: Mudanza uuid=%s no encontrada", mudanza_uuid)
        return

    if mudanza.estado == Mudanza.Estado.CONFIRMADA:
        logger.info("webhook/mp: Mudanza uuid=%s ya estaba CONFIRMADA — sin cambios", mudanza_uuid)
        return

    if mudanza.estado != Mudanza.Estado.PRESUPUESTADA:
        logger.warning(
            "webhook/mp: Mudanza uuid=%s está en estado=%s, se esperaba PRESUPUESTADA — igual se confirma",
            mudanza_uuid,
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
