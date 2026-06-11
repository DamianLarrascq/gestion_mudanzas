from __future__ import annotations
import json
import logging
from django.http import JsonResponse, HttpRequest
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from gestion.models.catalogo import CatalogoItem
from public.forms import SolicitudPresupuestoForm
from public.services.solicitud_service import procesar_solicitud_landing
from gestion.services.chatbot_service import ChatbotHandler
from gestion.models.chatbot import SesionChatbot

logger = logging.getLogger(__name__)
_MAX_TEXTO_LONGITUD = 1000


def landing(request):
    """
    GET /

    Contexto entregado al template:
        catalogo_items: list[dict]
            - id              int
            - nombre          str
            - volumen_m3      str
            - peso_estimado_kg str
    """
    catalogo_items = list(
        CatalogoItem.objects.values("id", "nombre", "volumen_m3", "peso_estimado_kg")
        .order_by("nombre")
    )
    return render(request, "public/landing.html", {"catalogo_items": catalogo_items})


@require_POST
def solicitar_presupuesto(request):
    """
    POST /presupuesto/solicitar/
    Content-Type: application/json

    Body: ver contrato en frontend_handoff_landing.md

    Respuestas:
        200 { ok, pago_url, monto_total, monto_senia, mudanza_id }
        422 { ok, errores }   — validación
        502 { ok, errores }   — error MercadoPago
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse(
            {"ok": False, "errores": {"__all__": ["Payload inválido."]}},
            status=400,
        )

    form = SolicitudPresupuestoForm(body)
    if not form.is_valid():
        return JsonResponse({"ok": False, "errores": form.errors}, status=422)

    inventario_raw = body.get("inventario", [])

    try:
        resultado = procesar_solicitud_landing(form.cleaned_data, inventario_raw)
    except ValidationError as exc:
        return JsonResponse(
            {"ok": False, "errores": {"__all__": exc.messages}},
            status=422,
        )
    except RuntimeError as exc:
        return JsonResponse(
            {"ok": False, "errores": {"__all__": [str(exc)]}},
            status=502,
        )

    return JsonResponse({"ok": True, **resultado})


def presupuesto_gracias(request):
    """
    GET /presupuesto/gracias/
    Página de confirmación post-pago exitoso.
    MercadoPago redirige aquí con ?payment_id=...&status=approved

    Contexto entregado al template:
        payment_id:  str | None   — ID del pago en MP
        status:      str | None   — "approved" | "pending" etc.
    """
    return render(request, "public/gracias.html", {
        "payment_id": request.GET.get("payment_id"),
        "status": request.GET.get("status"),
    })


"""
ChatbotWebView: endpoint REST para el pop-up del frontend.

Contrato:
    POST /api/chatbot/mensaje/
    Content-Type: application/json
    Body: { "texto": "Hola, quiero un presupuesto." }

    Response 200:
    {
        "mensajes": ["Texto 1", "Texto 2", ...],
        "atencion_manual": false,
        "flujo": "LANDING"
    }

    Response 400: { "error": "El campo 'texto' es requerido." }
    Response 500: { "error": "Error interno del servidor." }
"""


@method_decorator(csrf_exempt, name="dispatch")
class ChatbotWebView(View):
    """
    Endpoint HTTP para el pop-up de chat del sitio público.

    Usa session_key como canal_id para identificar al visitante de forma
    anónima sin requerir autenticación. La sesión Django se crea
    automáticamente en el primer request.
    """

    def get(self, request: HttpRequest) -> JsonResponse:
        """
        Retorna el estado actual de la sesión sin procesar ningún mensaje.
        El frontend lo llama al montar el pop-up para saber si el input
        debe estar habilitado o no.

        Response 200:
        {
            "atencion_manual": false,
            "tiene_historial": true
        }
        """
        if not request.session.session_key:
            # Sesión nueva: nunca hubo interacción
            return JsonResponse({"atencion_manual": False, "tiene_historial": False})

        from gestion.models.chatbot import SesionChatbot

        sesion = SesionChatbot.objects.filter(
            canal_id=request.session.session_key,
            canal=SesionChatbot.Canal.WEB,
        ).first()

        if sesion is None:
            return JsonResponse({"atencion_manual": False, "tiene_historial": False})

        return JsonResponse({
            "atencion_manual": sesion.atencion_manual,
            "tiene_historial": sesion.mensajes.exists(),
        })

    def post(self, request: HttpRequest) -> JsonResponse:
        # Asegurar que la sesión existe para tener un canal_id estable
        if not request.session.session_key:
            request.session.create()

        canal_id = request.session.session_key

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "JSON inválido."}, status=400)

        texto = body.get("texto", "").strip()

        if not texto:
            return JsonResponse(
                {"error": "El campo 'texto' es requerido."}, status=400
            )

        if len(texto) > _MAX_TEXTO_LONGITUD:
            return JsonResponse(
                {"error": f"El mensaje no puede superar {_MAX_TEXTO_LONGITUD} caracteres."},
                status=400,
            )

        try:
            resultado = ChatbotHandler.procesar(
                canal_id=canal_id,
                canal=SesionChatbot.Canal.WEB,
                texto=texto,
            )
        except Exception:
            logger.exception("Error en ChatbotWebView para sesión %s.", canal_id)
            return JsonResponse({"error": "Error interno del servidor."}, status=500)

        return JsonResponse(
            {
                "mensajes": resultado.mensajes,
                "atencion_manual": resultado.atencion_manual,
                "flujo": resultado.flujo,
            },
            status=200,
        )
