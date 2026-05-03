from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from django.db.models import Count, DecimalField, OuterRef, Q, QuerySet, Subquery, Sum
from django.db.models.functions import Coalesce
from gestion.models.clientes import Cliente
from gestion.models.mudanzas import Mudanza
from gestion.models.presupuestos import Presupuesto

# Clasificacion de clientes

_ESTADOS_ACTIVO = [Mudanza.Estado.CONFIRMADA, Mudanza.Estado.EN_CURSO]
_ESTADOS_HISTORICO = [Mudanza.Estado.COMPLETADA]
_ESTADOS_POTENCIAL = [Mudanza.Estado.BORRADOR, Mudanza.Estado.PRESUPUESTADA]

# Un cliente es "activo" si tiene al menos una mudanza CONFIRMADA o EN_CURSO.
# Un cliente es "potencial" si NO tiene mudanzas completadas y tiene alguna en
# BORRADOR o PRESUPUESTADA.
# El resto son clientes con historial (completadas, canceladas, pospuestas).

def obtener_metricas_clientes() -> dict:
    """
    KPIs generales del módulo Clientes.

    Retorna:
        total          (int)  – total de clientes registrados
        activos        (int)  – con mudanza CONFIRMADA o EN_CURSO ahora mismo
        potenciales    (int)  – sin mudanza completada, con presupuesto/borrador abierto
        con_historial  (int)  – tienen al menos una mudanza COMPLETADA
    """
    total = Cliente.objects.count()

    activos = (
        Cliente.objects.filter(mudanzas__estad__in=_ESTADOS_ACTIVO).distinct().count()
    )

    con_historial = (
        Cliente.objects.filter(mudanzas__estado=Mudanza.Estado.COMPLETADA).distinct().count()
    )

    potenciales = (
        Cliente.objects.filter(mudanzas__estado__in=_ESTADOS_POTENCIAL).exclude(mudanzas__estado=Mudanza.Estado.COMPLETADA).distinct().count()
    )

    return {
        'total': total,
        'activos': activos,
        'potenciales': potenciales,
        'con_historial': con_historial,
    }

# Filtros y listado

@dataclass(frozen=True)
class FiltrosCliente:
    q: str = ""
    segmento: str = ""   # "activo" | "potencial" | "con_historial" | ""
    page: int = 1
    page_size: int = 25


def obtener_clientes_filtrados(filtros: FiltrosCliente) -> dict:
    """
    Retorna el contexto listo para la vista de listado de clientes.

    El queryset anota:
        - total_mudanzas(int)
        - mudanzas_completadas(int)
        - inversion_total(Decimal) – suma de Presupuesto.total de mudanzas COMPLETADAS
    """
    # Subquery: suma de presupuestos de mudanzas completadas de este cliente
    inversion_sq = (
        Presupuesto.objects.filter(
            mudanza__cliente=OuterRef("pk"),
            mudanza__estado=Mudanza.Estado.COMPLETADA,
        )
        .values("mudanza__cliente")
        .annotate(s=Sum("total"))
        .values("s")
    )

    qs = (
        Cliente.objects.annotate(
            total_mudanzas=Count("mudanzas", distinct=True),
            mudanzas_completadas=Count(
                "mudanzas",
                filter=Q(mudanzas__estado=Mudanza.Estado.COMPLETADA),
                distinct=True,
            ),
            inversion_total=Coalesce(
                Subquery(inversion_sq, output_field=DecimalField()),
                Decimal("0"),
            ),
        )
        .order_by("-creado_en")
    )

    qs = _aplicar_filtro_texto(qs, filtros.q)
    qs = _aplicar_filtro_segmento(qs, filtros.segmento)

    total = qs.count()
    pagina = _paginar(qs, filtros.page, filtros.page_size)

    return {
        "clientes": [_serializar_cliente_fila(c) for c in pagina],
        "metricas": obtener_metricas_clientes(),
        "paginacion": _construir_paginacion(total, filtros.page, filtros.page_size),
        "filtros_activos": {"q": filtros.q, "segmento": filtros.segmento},
        "opciones_segmento": _opciones_segmento(),
    }

# Detalles de cliente con historial

def obtener_detalle_cliente(cliente_id: int) -> dict:
    """
    Retorna el perfil completo de un cliente con su historial de mudanzas.
    Raises:
        Cliente.DoesNotExist - si el id no existe (la vista debe manejar el 404)
    """
    cliente = Cliente.objects.get(pk=cliente_id)
    mudanzas = _obtener_historial_mudanzas(cliente_id)
    inversion_total = sum(m['monto'] for m in mudanzas if m['monton'] is not None)

    return {
        'cliente': _serializar_cliente_detalle(cliente),
        'historial': mudanzas,
        'resumen': _construir_resumen_cliente(mudanzas, inversion_total),
    }

def _obtener_historial_mudanzas(cliente_id: int) -> list[dict]:
    qs = (
        Mudanza.objects.filter(cliente_id=cliente_id).select_related('origen', 'destino', 'camion', 'presupuesto').order_by('-fecha_hora')
    )

    return [_serializar_mudanza_historial(m) for m in qs]

def _construir_resumen_cliente(mudanzas: list[dict], inversion_total: Decimal) -> dict:
    completadas = sum(1 for m in mudanzas if m['estado_valor'] == Mudanza.Estado.COMPLETADA)
    canceladas = sum(1 for m in mudanzas if m['estado_valor'] == Mudanza.Estado.CANCELADA)
    activa_ahora = any(
        m['estado_valor'] in _ESTADOS_ACTIVO for m in mudanzas
    )

    return {
        'total_mudanzas': len(mudanzas),
        'completadas': completadas,
        'canceladas': canceladas,
        'activa_ahora': activa_ahora,
        'inversion_total_display': f'${inversion_total:,.0f}',
        'inversion_total_raw': inversion_total,
    }

# Serializers internos

_ESTADO_BADGE: dict[str, str] = {
    Mudanza.Estado.BORRADOR: "badge-secondary",
    Mudanza.Estado.PRESUPUESTADA: "badge-info",
    Mudanza.Estado.CONFIRMADA: "badge-primary",
    Mudanza.Estado.EN_CURSO: "badge-warning",
    Mudanza.Estado.COMPLETADA: "badge-success",
    Mudanza.Estado.CANCELADA: "badge-danger",
    Mudanza.Estado.POSPUESTA: "badge-dark",
}

_ESTADO_LABEL = dict(Mudanza.Estado.choices)

_MESES_ES = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun",
             "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _fmt_fecha(dt) -> str:
    """'20 Abr 2025' o '-' si None."""
    if dt is None:
        return "-"
    return f"{dt.day} {_MESES_ES[dt.month]} {dt.year}"


def _serializar_cliente_fila(c: Cliente) -> dict:
    """Versión compacta para tablas de listado."""
    return {
        "id": c.pk,
        "nombre_completo": c.nombre_completo,
        "telefono": c.telefono,
        "email": c.email or "-",
        "total_mudanzas": c.total_mudanzas,          # anotado
        "mudanzas_completadas": c.mudanzas_completadas,  # anotado
        "inversion_total_display": f"${c.inversion_total:,.0f}",
        "inversion_total_raw": c.inversion_total,
        "creado_en_display": _fmt_fecha(c.creado_en.date()),
        "url_detalle": f"/gestion/clientes/{c.pk}/",
    }


def _serializar_cliente_detalle(c: Cliente) -> dict:
    """Versión completa para la página de perfil."""
    return {
        "id": c.pk,
        "nombre_completo": c.nombre_completo,
        "dni": c.dni or "-",
        "telefono": c.telefono,
        "email": c.email or "-",
        "fecha_nacimiento_display": _fmt_fecha(c.fecha_nacimiento) if c.fecha_nacimiento else "-",
        "cliente_desde_display": _fmt_fecha(c.creado_en.date()),
    }


def _serializar_mudanza_historial(m: Mudanza) -> dict:
    """Una fila del historial de mudanzas de un cliente."""
    presupuesto = getattr(m, "presupuesto", None)
    monto = presupuesto.total if presupuesto else None

    return {
        "id": m.pk,
        "url_detalle": f"/gestion/mudanzas/{m.pk}/",
        "fecha_display": _fmt_fecha(m.fecha_hora.date()),
        "fecha_iso": m.fecha_hora.isoformat(),
        "ruta": _fmt_ruta(m.origen, m.destino),
        "camion_display": m.camion.patente if m.camion else "Sin asignar",
        "estado_valor": m.estado,
        "estado_label": _ESTADO_LABEL[m.estado],
        "estado_badge_class": _ESTADO_BADGE.get(m.estado, "badge-secondary"),
        "monto": monto,
        "monto_display": f"${monto:,.0f}" if monto is not None else "-",
        "senia_pagada": m.senia_pagada,
    }


def _fmt_ruta(origen, destino) -> str:
    orig = origen.localidad if origen else "-"
    dest = destino.localidad if destino else "-"
    return f"{orig} → {dest}"


# ---------------------------------------------------------------------------
# Helpers de filtrado y paginación
# ---------------------------------------------------------------------------

def _aplicar_filtro_texto(qs: QuerySet, q: str) -> QuerySet:
    if not q or not q.strip():
        return qs
    t = q.strip()
    return qs.filter(
        Q(nombre_completo__icontains=t)
        | Q(dni__icontains=t)
        | Q(telefono__icontains=t)
        | Q(email__icontains=t)
    )


def _aplicar_filtro_segmento(qs: QuerySet, segmento: str) -> QuerySet:
    match segmento:
        case "activo":
            return qs.filter(mudanzas__estado__in=_ESTADOS_ACTIVO).distinct()
        case "potencial":
            return (
                qs.filter(mudanzas__estado__in=_ESTADOS_POTENCIAL)
                .exclude(mudanzas__estado=Mudanza.Estado.COMPLETADA)
                .distinct()
            )
        case "con_historial":
            return qs.filter(mudanzas__estado=Mudanza.Estado.COMPLETADA).distinct()
        case _:
            return qs


def _paginar(qs: QuerySet, page: int, page_size: int) -> QuerySet:
    page = max(1, page)
    offset = (page - 1) * page_size
    return qs[offset: offset + page_size]


def _construir_paginacion(total: int, page: int, page_size: int) -> dict:
    total_paginas = max(1, -(-total // page_size))
    return {
        "total_registros": total,
        "pagina_actual": page,
        "total_paginas": total_paginas,
        "tiene_anterior": page > 1,
        "tiene_siguiente": page < total_paginas,
        "pagina_anterior": page - 1,
        "pagina_siguiente": page + 1,
    }


def _opciones_segmento() -> list[dict]:
    return [
        {"valor": "activo",        "label": "Activos"},
        {"valor": "potencial",     "label": "Potenciales"},
        {"valor": "con_historial", "label": "Con historial"},
    ]