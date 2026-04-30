from __future__ import annotations
from dataclasses import dataclass
from django.db.models import Count, Q, QuerySet
from gestion.models.mudanzas import Mudanza

_ESTADO_BADGE: dict[str, str] = {
    Mudanza.Estado.BORRADOR: "badge-secondary",
    Mudanza.Estado.PRESUPUESTADA: "badge-info",
    Mudanza.Estado.CONFIRMADA: "badge-primary",
    Mudanza.Estado.EN_CURSO: "badge-warning",
    Mudanza.Estado.COMPLETADA: "badge-success",
    Mudanza.Estado.CANCELADA: "badge-danger",
    Mudanza.Estado.POSPUESTA: "badge-muted",
}

_DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
_MESES_ES = [
    "", "Ene", "Feb", "Mar", "Abr", "May", "Jun",
    "Jul", "Ago", "Sep", "Oct", "Nov", "Dic",
]

@dataclass(frozen=True)
class FiltrosMudanza:
    """
    Parámetros de búsqueda validados. Construir desde la request en la vista.
    """
    q: str = ""
    estado: str = ""
    page: int = 1
    page_size: int = 20

def _formatear_fecha(dt) -> str:
    """
    Recibe datetime o None, retorna "Lunes 20, Abr"
    """
    if dt is None:
        return "-"
    dia_semana = _DIAS_ES[dt.weekday()]
    mes = _MESES_ES[dt.moth]
    return f'{dia_semana} {dt.day}, {mes}'

def _formatear_ruta(origen, destino) -> str:
    orig = origen.localidad if origen else "-"
    dest = destino.localidad if destino else "-"
    return f'{orig} → {dest}'

# Capa de servicio

def obtener_mudanzas_filtradas(filtros: FiltrosMudanza) -> dict:
    """
    Retorna el contexto listo para la vista de listado.

    Estrategia de consulta:
    - Un solo hit al ORM con select_related para cliente, camión, origen, destino.
    - Prefetch de asignaciones con Count anotado para evitar N+1.
    - Paginación manual (sin django.core.paginator) para retornar metadatos explícitos.
    """

    qs = (
        Mudanza.objects.select_related('cliente', 'camion', 'origen', 'destino').annotate(total_operarios=Count('asignaciones')).order_by('-fecha_hora')
    )

    qs = _aplicar_filtro_texto(qs, filtros.q)
    qs = _aplicar_filtro_estado(qs, filtros.estado)

    total = qs.count()
    mudanzas_pagina = _paginar(qs, filtros.page, filtros.page_size)

    return {
        "mudanzas": [_serializar_mudanza(m) for m in mudanzas_pagina],
        "paginacion": _construir_paginacion(total, filtros.page, filtros.page_size),
        'filtros_activos': {
            'q': filtros.q,
            'estado': filtros.estado,
        },
        "opciones_estado": _opciones_estado(),
    }

# Helpers

def _aplicar_filtro_texto(qs: QuerySet, q: str) -> QuerySet:
    if not q or not q.strip():
        return qs
    termino = q.strip()
    return qs.filter(
        Q(cliente__nombre_completo__icontains=termino)
        | Q(cliente__telefono__icontains=termino)
        | Q(origen__localidad__icontains=termino)
        | Q(destino__localidad__icontains=termino)
        | Q(camion__patente__icontains=termino)
    )

def _aplicar_filtro_estado(qs: QuerySet, estado: str) -> QuerySet:
    if not estado or estado not in Mudanza.Estado.values:
        return qs
    return qs.filter(estado=estado)

def _paginar(qs: QuerySet, page: int, page_size: int) -> QuerySet:
    page = max(1, page)
    offset = (page - 1) * page_size
    return qs[offset: offset + page_size]

def _serializar_mudanza(m: Mudanza) -> dict:
    return {
        "id": m.pk,
        "cliente_nombre": m.cliente.nombre_completo,
        "ruta": _formatear_ruta(m.origen, m.destino),
        "fecha_display": _formatear_fecha(m.fecha_hora),
        "fecha_iso": m.fecha_hora.isoformat(),          # para ordenamiento JS si se necesita
        "camion_display": m.camion.patente if m.camion else "Sin asignar",
        "total_operarios": m.total_operarios,           # ya anotado, sin query extra
        "estado_valor": m.estado,
        "estado_label": m.get_estado_display(),
        "estado_badge_class": _ESTADO_BADGE.get(m.estado, "badge-secondary"),
        "senia_pagada": m.senia_pagada,
    }

def _construir_paginacion(total: int, page: int, page_size: int) -> dict:
    total_paginas = max(1, -(-total // page_size))      # ceil sin math
    return {
        "total_registros": total,
        "pagina_actual": page,
        "total_paginas": total_paginas,
        "tiene_anterior": page > 1,
        "tiene_siguiente": page < total_paginas,
        "pagina_anterior": page - 1,
        "pagina_siguiente": page + 1,
    }


def _opciones_estado() -> list[dict]:
    """Para poblar el <select> de filtro en el frontend."""
    return [
        {"valor": e.value, "label": e.label}
        for e in Mudanza.Estado
    ]