from decimal import Decimal

from django.core.exceptions import ValidationError

from gestion.models import Mudanza, Presupuesto, TarifaBase
from .inventory import calcular_volumen_total


def _tarifa_vigente() -> TarifaBase:
    tarifa = TarifaBase.objects.filter(activa=True).order_by("-vigente_desde").first()
    if not tarifa:
        raise ValidationError("No hay ninguna tarifa activa configurada.")
    return tarifa


def _recargo_pisos(mudanza: Mudanza, tarifa: TarifaBase) -> Decimal:
    recargo = Decimal("0")
    if mudanza.origen and mudanza.origen.piso > 0 and not mudanza.origen.tiene_ascensor:
        recargo += tarifa.recargo_piso * mudanza.origen.piso
    if mudanza.destino and mudanza.destino.piso > 0 and not mudanza.destino.tiene_ascensor:
        recargo += tarifa.recargo_piso * mudanza.destino.piso
    return recargo


def calcular_presupuesto(mudanza: Mudanza) -> Presupuesto:
    if not mudanza.distancia_km:
        raise ValidationError("La mudanza no tiene distancia calculada.")

    tarifa = _tarifa_vigente()

    costo_distancia = tarifa.precio_por_km * mudanza.distancia_km
    costo_peajes = Decimal("0")
    costo_ayudantes = Decimal("0")

    if mudanza.necesita_ayudantes:
        cantidad_ayudantes = (
            mudanza.asignaciones
            .filter(rol="AYUDANTE")
            .count()
        )
        costo_ayudantes = tarifa.precio_ayudante * cantidad_ayudantes

    costo_camion = Decimal("0")
    recargo_pisos = _recargo_pisos(mudanza, tarifa)

    total = (
        costo_distancia
        + costo_peajes
        + costo_ayudantes
        + costo_camion
        + recargo_pisos
    )

    presupuesto, _ = Presupuesto.objects.update_or_create(
        mudanza=mudanza,
        defaults={
            "tarifa": tarifa,
            "costo_distancia": costo_distancia,
            "costo_peajes": costo_peajes,
            "costo_ayudantes": costo_ayudantes,
            "costo_camion": costo_camion,
            "recargo_pisos": recargo_pisos,
            "total": total,
        },
    )
    return presupuesto