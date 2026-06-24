from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Literal
from django.urls import reverse
from django.utils import timezone
from gestion.models.flota import Camion
from gestion.models.mudanzas import Mudanza

# Constantes

_DIAS_ALERTA_VENCIMIENTO = 30
EstadoOperativo = Literal['DISPONIBLE', 'EN_SERVICIO', 'EN_TALLER']
_ESTADO_OPERATIVO_LABEL: dict[EstadoOperativo, str] = {
    'DISPONIBLE': "Disponible",
    'EN_SERVICIO': 'En servicio',
    'EN_TALLER': 'En taller',
}
_ESTADO_OPERATIVO_BADGE: dict[EstadoOperativo, str] = {
    'DISPONIBLE': 'badge-success',
    'EN_SERVICIO': 'badge-warning',
    'EN_TALLER': 'badge-danger',
}


# Helpers

@dataclass(frozen=True)
class _EstadoDoc:
    estado: Literal['OK', 'POR_VENCER', 'VENCIDO', 'SIN_DATOS']
    label: str
    badge: str


def _evaluar_documento(fecha: date | None, hoy: date, nombre: str) -> _EstadoDoc:
    """
    Clasifica un documento por proximidad a su vencimiento.
    Retorna label y badge listos para el frontend.
    """
    if fecha is None:
        return _EstadoDoc('SIN_DATOS', f'{nombre}: sin fecha cargada', 'badge-secondary')

    dias_restantes = (fecha - hoy).days

    if dias_restantes < 0:
        return _EstadoDoc(
            'VENCIDO',
            f"{nombre}: VENCIDO el {fecha.strftime('%d/%m/%Y')}",
            'badge-danger',
        )
    if dias_restantes <= _DIAS_ALERTA_VENCIMIENTO:
        return _EstadoDoc(
            'POR_VENCER',
            f"{nombre}: vence en {dias_restantes} dia{'s' if dias_restantes != 1 else ''}",
            'badge-warning',
        )

    return _EstadoDoc(
        'OK',
        f"{nombre}: vigente hasta {fecha.strftime('%d/%m/%Y')}",
        'badge-success'
    )


def _documentacion_critica(docs: list[_EstadoDoc]) -> _EstadoDoc:
    """
    De todos los documentos, devuelve el de mayor severidad
    para mostrar el estado general en la card.
    Prioridad: VENCIDO > POR_VENCER > SIN_DATOS > OK
    """
    prioridad = {"VENCIDO": 0, "POR_VENCER": 1, "SIN_DATOS": 2, "OK": 3}
    return min(docs, key=lambda d: prioridad[d.estado])


# Estado operativo

def _resolver_estado_operativo(camion: Camion, patentes_en_servicio: set[int]) -> EstadoOperativo:
    """
    Determina el estado operativo con esta precedencia:
      1. en_taller=True → EN_TALLER (estado explícito)
      2. mudanza EN_CURSO → EN_SERVICIO
      3. resto → DISPONIBLE
    """
    if camion.pk in patentes_en_servicio:
        return "EN_SERVICIO"
    return "DISPONIBLE"


# Serializacion

def _serializar_camion(camion: Camion, estado_operativo: EstadoOperativo, hoy: date) -> dict:
    vtv = _evaluar_documento(camion.vtv_fecha_vencimiento, hoy, "VTV")
    seguro = _evaluar_documento(camion.seguro_fecha_vencimiento, hoy, "Seguro")
    patente_doc = _evaluar_documento(camion.patente_fecha_vencimiento, hoy, "Patente")

    doc_critica = _documentacion_critica([vtv, seguro, patente_doc])

    return {
        # Identificación
        "id": camion.pk,
        "patente": camion.patente,
        "modelo": camion.modelo,
        "anio": camion.anio or "—",
        "categoria_label": camion.get_categoria_display(),
        "capacidad_volumen_m3": str(camion.capacidad_volumen_m3),
        "capacidad_peso_kg": str(camion.capacidad_peso_kg),

        # Estado operativo
        "estado_operativo": estado_operativo,
        "estado_operativo_label": _ESTADO_OPERATIVO_LABEL[estado_operativo],
        "estado_operativo_badge": _ESTADO_OPERATIVO_BADGE[estado_operativo],

        # Documentación — detalles por documento
        "vtv_label": vtv.label,
        "vtv_badge": vtv.badge,
        "seguro_label": seguro.label,
        "seguro_badge": seguro.badge,
        "patente_doc_label": patente_doc.label,
        "patente_doc_badge": patente_doc.badge,

        # Documentación — resumen para la card (el peor estado)
        "estado_documentacion": doc_critica.label,
        "estado_documentacion_badge": doc_critica.badge,
        "documentacion_tiene_alerta": doc_critica.estado in ("VENCIDO", "POR_VENCER"),

        # URL de gestión
        "url_detalle": reverse("gestion:camion_detail", kwargs={"pk": camion.pk}),
    }


# Entrypoint

def obtener_estado_flota(hoy: date | None = None) -> dict:
    """
    Retorna el contexto completo para la vista de monitoreo de flota.

    Estrategia ORM:
    - Un único queryset sobre Camion.activo=True.
    - Un segundo queryset para IDs de camiones en mudanzas EN_CURSO hoy
      (no un prefetch, para evitar traer objetos Mudanza innecesarios).
    - Sin N+1: toda la lógica de documentación es Python puro sobre fechas ya cargadas.
    """
    hoy = hoy or timezone.localdate()

    camiones = list(
        Camion.objects.filter(activo=True).order_by("patente")
    )

    # IDs de camiones que tienen una mudanza EN_CURSO hoy — 1 sola query
    en_servicio_ids: set[int] = set(
        Mudanza.objects.filter(
            estado=Mudanza.Estado.EN_CURSO,
            fecha_hora__date=hoy,
            camion__isnull=False,
        ).values_list("camion_id", flat=True)
    )

    serializados = [
        _serializar_camion(c, _resolver_estado_operativo(c, en_servicio_ids), hoy)
        for c in camiones
    ]

    # Agrupamiento — listas separadas, listas para iterar en template
    grupos: dict[EstadoOperativo, list[dict]] = {
        "DISPONIBLE": [],
        "EN_SERVICIO": [],
        "EN_TALLER": [],
    }
    for c in serializados:
        grupos[c["estado_operativo"]].append(c)

    # Resumen para los contadores del encabezado
    total = len(serializados)
    con_alerta_doc = sum(1 for c in serializados if c["documentacion_tiene_alerta"])

    return {
        "grupos_flota": [
            {
                "estado_operativo": estado,
                "estado_operativo_label": _ESTADO_OPERATIVO_LABEL[estado],
                "estado_operativo_badge": _ESTADO_OPERATIVO_BADGE[estado],
                "camiones": lista,
                "cantidad": len(lista),
            }
            for estado, lista in grupos.items()
        ],
        "resumen": {
            "total_activos": total,
            "disponibles": len(grupos["DISPONIBLE"]),
            "en_servicio": len(grupos["EN_SERVICIO"]),
            "en_taller": len(grupos["EN_TALLER"]),
            "con_alerta_documentacion": con_alerta_doc,
        },
    }

def obtener_camiones_disponibles_para_fecha(fecha: date) -> list[dict]:
    """
    Retorna camiones aptos para asignar a una mudanza en la fecha dada.

    Un camion es elegible si cumple TODAS estas condiciones:
        1. activo=True
        2. No tiene una mudanza CONFIRMADA o EN_CURSO en esa fecha

    Args:
        fecha: Fecha de la mudanza a crear.

    Returns:
        Lista de dicts listos para poblar el <select> del formulario.
    """

    hoy = timezone.localdate()

    ocupados_ids: set[int] = set(
        Mudanza.objects.filter(
            fecha_hora__date=fecha,
            estado__in=[Mudanza.Estado.CONFIRMADA, Mudanza.Estado.EN_CURSO],
            camion__isnull=False,
        ).values_list('camion_id', flat=True)
    )

    camiones = Camion.objects.filter(activo=True).order_by('patente')

    return [
        _serializar_camion_selector(c, c.pk in ocupados_ids, hoy) for c in camiones
    ]

def _serializar_camion_selector(camion: Camion, ocupado: bool, hoy: date) -> dict:
    """
    Version reducida de _serializar_camion para el selector del formulario.
    Incluye solo lo que necesita el frontend para mostrar la opcion y advertir.
    """

    vtv = _evaluar_documento(camion.vtv_fecha_vencimiento, hoy, 'VTV')
    seguro = _evaluar_documento(camion.seguro_fecha_vencimiento, hoy, 'Seguro')
    patente_doc = _evaluar_documento(camion.patente_fecha_vencimiento, hoy, 'Patente')
    doc_critica = _documentacion_critica([vtv, seguro, patente_doc])

    return {
        'id': camion.pk,
        'patente': camion.patente,
        'categoria_label': camion.get_categoria_display(),
        'capacidad_volumen_m3': str(camion.capacidad_volumen_m3),
        'capacidad_peso_kg': str(camion.capacidad_peso_kg),
        'disponible': not ocupado,
        'disponible_label': 'Disponible' if not ocupado else 'Ocupado ese dia',
        'disponible_badge': 'badge-success' if not ocupado else 'badge-danger',
        'documentacion_alerta': doc_critica.estado in ('VENCIDO', 'POR_VENCER'),
        'documentacion_label': doc_critica.label,
        'documentacion_badge': doc_critica.badge,
    }