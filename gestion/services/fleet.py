from gestion.models import Camion, Mudanza
from .inventory import calcular_volumen_total, calcular_peso_total

def sugerir_camion(mudanza: Mudanza) -> Camion | None:
    volumen = calcular_volumen_total(mudanza)
    peso = calcular_peso_total(mudanza)

    return (
        Camion.objects.filter(
            activo=True,
            capacidad_volumen_m3__gte=volumen,
            capacidad_peso_kg__gte=peso,
        ).order_by('capacidad_volumen_m3').first()
    )