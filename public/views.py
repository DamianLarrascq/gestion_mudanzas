from __future__ import annotations
import json
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from gestion.models.catalogo import CatalogoItem
from public.forms import SolicitudPresupuestoForm
from public.services.solicitud_service import procesar_solicitud_landing

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
