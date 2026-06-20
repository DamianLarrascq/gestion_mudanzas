"""
Lógica de lectura y serialización para la vista de Configuración de Tarifas.
La activación de una nueva tarifa se gestiona aquí con select_for_update
para evitar condiciones de carrera.
"""
from __future__ import annotations
from django.db import transaction
from gestion.models.presupuestos import TarifaBase


# ── Serialización ──────────────────────────────────────────────────────────

def _serializar_tarifa(t: TarifaBase) -> dict:
    return {
        "id": t.pk,
        "nombre": t.nombre,
        "vigente_desde": t.vigente_desde.strftime("%d/%m/%Y"),
        "vigente_desde_iso": t.vigente_desde.isoformat(),
        "activa": t.activa,
        "permite_caba_feriados": t.permite_caba_feriados,
        # Precios básicos
        "precio_por_km": str(t.precio_por_km),
        "precio_ayudante": str(t.precio_ayudante),
        "recargo_piso": str(t.recargo_piso),
        # Recargos (multiplicadores)
        "recargo_hora_pico": str(t.recargo_hora_pico),
        "recargo_fin_de_semana": str(t.recargo_fin_de_semana),
        # Costos operativos
        "seguro_camion": str(t.seguro_camion),
        "empleado_art": str(t.empleado_art),
        "empleado_seguro_riesgo": str(t.empleado_seguro_riesgo),
        "empleado_seguro_ayudante": str(t.empleado_seguro_ayudante),
        "salario_conductor": str(t.salario_conductor),
        "salario_ayudante": str(t.salario_ayudante),
        # URL
        "url_editar": f"/gestion/configuracion/tarifas/{t.pk}/editar/",
    }


# ── Queries públicas ───────────────────────────────────────────────────────

def obtener_contexto_config_tarifas() -> dict:
    """
    Contexto completo para ConfiguracionTarifaView.

    Retorna:
        tarifa_activa   (dict | None) – tarifa vigente serializada
        historial       (list[dict])  – últimas 10 tarifas, ordenadas -vigente_desde
        puede_crear     (bool)        – siempre True; la UI puede ocultarlo si hay activa
    """
    tarifas = list(TarifaBase.objects.order_by("-vigente_desde")[:10])
    activa = next((t for t in tarifas if t.activa), None)

    return {
        "tarifa_activa": _serializar_tarifa(activa) if activa else None,
        "historial": [_serializar_tarifa(t) for t in tarifas],
        "puede_crear": True,
    }


def activar_tarifa(tarifa_id: int) -> dict:
    """
    Activa la tarifa indicada y desactiva todas las demás.
    Operación atómica con select_for_update.

    Returns:
        dict con la tarifa recién activada serializada.

    Raises:
        TarifaBase.DoesNotExist
    """
    with transaction.atomic():
        tarifa = TarifaBase.objects.select_for_update().get(pk=tarifa_id)
        TarifaBase.objects.exclude(pk=tarifa_id).update(activa=False)
        tarifa.activa = True
        tarifa.save(update_fields=["activa"])

    return _serializar_tarifa(tarifa)
