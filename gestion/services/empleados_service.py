from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
from django.db.models import Count, Q, QuerySet
from django.urls import reverse
from django.utils import timezone
from gestion.models.flota import Empleado
from gestion.models.mudanzas import Mudanza

_UMBRAL_ALERTA_DIAS = 15
_ROL_LABEL: dict[str, str] = dict(Empleado.Rol.choices)
_DISPONIBILIDAD_BADGE: dict[str, str] = {
    'libre': 'badge-success',
    'ocupado': 'badge-warning',
    'no_disponible': 'badge-danger',
}

@dataclass(frozen=True)
class FiltrosEmpleado:
    """
    Parametros validados de busqueda. Construir desde la request en la vista.
    """
    q: str = ""
    rol: str = ""
    solo_disponibles: bool = False
    page: int = 1
    page_size: int = 25

# Helpers

def _dias_para_vencer(fecha: date | None, hoy: date) -> int | None:
    """
    Dias hasta que vence una fecha. Negativo = ya vencio. None = sin dato.
    """
    if fecha is None:
        return None
    return (fecha - hoy).days

def _estado_licencia(dias: int | None) -> dict:
    """
    Retorna el bloque de licencia listo para renderizar.
    Aplica solo a conductores; para otros roles el bloque es neutro.
    """
    if dias is None:
        return {
            'licencia_texto': 'Sin datos',
            'licencia_badge': 'badge-secondary',
            'alerta_licencia': False,
        }
    if dias < 0:
        return {
            'licencia_texto': f'Vencida hace {abs(dias)} dias',
            'licencia_badge': 'badge-danger',
            'alerta_licencia': True,
        }
    if dias <= _UMBRAL_ALERTA_DIAS:
        return {
            'licencia_texto': f'Vence en {dias} dias',
            'licencia_badge': 'badge-warning',
            'alerta_licencia': True,
        }
    return {
        'licencia_texto': f'Vence en {dias} dias',
        'licencia_badge': 'badge-success',
        'alerta_licencia': False,
    }

def _estado_seguro(campo_nombre: str, dias: int | None) -> dict:
    """
    Bloque generico para cualquier seguro/art con vencimiento.
    """
    if dias is None:
        return {
            'texto': 'Sin datos',
            'badge': 'badge-secondary',
            'vencido': False,
        }
    if dias < 0:
        return {
            'texto': f'Vencido hace {abs(dias)} dias',
            'badge': 'badge-danger',
            'vencido': True,
        }
    if dias <= _UMBRAL_ALERTA_DIAS:
        return {
            'texto': f'Vence en {dias} dias',
            'badge': 'badge-warning',
            'vencido': False,
        }
    return {
        'texto': f'Vence en {dias} dias',
        'badge': 'badge-success',
        'vencido': False,
    }

def _calcular_disponibilidad(empleado: Empleado, fecha: date) -> dict:
    """
    Determina el estado de disponibilidad de un empleado para 'fecha'.
    Usa la anotacion 'mudanzas_en_fecha' inyectada por el queryset.
    """
    if not empleado.disponible:
        return {
            'disponibilidad_valor': 'no_disponible',
            'disponibilidad_label': 'No disponible',
            'disponibilidad_badge': _DISPONIBILIDAD_BADGE['no_disponible'],
        }

    ocupado = getattr(empleado, 'mudanzas_en_fecha', 0) > 0
    clave = 'ocupado' if ocupado else 'libre'
    labels = {
        'libre': 'Libre',
        'ocupado': 'En servicio'
    }

    return {
        'disponibilidad_valor': clave,
        'disponibilidad_label': labels[clave],
        'disponibilidad_badge': _DISPONIBILIDAD_BADGE[clave],
    }

def _serializar_empleado(emp: Empleado, hoy: date) -> dict:
    es_conductor = emp.rol == Empleado.Rol.CONDUCTOR

    dias_licencia = _dias_para_vencer(emp.licencia_fecha_vencimiento, hoy) if es_conductor else None
    licencia_block = _estado_licencia(dias_licencia) if es_conductor else {
        "licencia_texto": "N/A",
        "licencia_badge": "badge-secondary",
        "alerta_licencia": False,
    }

    dias_seguro_riesgo = _dias_para_vencer(emp.seguro_riesgo, hoy)
    dias_seguro_ayudante = _dias_para_vencer(emp.seguro_ayudante_carga, hoy)

    seguro_riesgo_block = _estado_seguro("seguro_riesgo", dias_seguro_riesgo)
    seguro_ayudante_block = _estado_seguro("seguro_ayudante_carga", dias_seguro_ayudante)

    # Flag consolidado: cualquier documento crítico con alerta
    tiene_alerta_documental = (
        licencia_block["alerta_licencia"]
        or seguro_riesgo_block["vencido"]
        or seguro_ayudante_block["vencido"]
        or not emp.art
    )

    return {
        "id": emp.pk,
        "nombre": emp.nombre,
        "dni": emp.dni,
        "rol_valor": emp.rol,
        "rol_label": _ROL_LABEL.get(emp.rol, emp.rol),
        "nro_licencia": emp.nro_licencia or "—",
        # Disponibilidad
        **_calcular_disponibilidad(emp, hoy),
        # Licencia (solo conductores)
        "es_conductor": es_conductor,
        **licencia_block,                    # licencia_texto, licencia_badge, alerta_licencia
        # Seguros
        "seguro_riesgo": seguro_riesgo_block,
        "seguro_ayudante": seguro_ayudante_block,
        "art_vigente": emp.art,
        # Flag consolidado para ícono de alerta en la fila
        "tiene_alerta_documental": tiene_alerta_documental,
        # URL detalle
        "url_detalle": reverse("gestion:empleado_detail", kwargs={"pk": emp.pk}),
    }

# Queryset base

def _qs_base(fecha: date) -> QuerySet:
    """
    Queryset anotado con `mudanzas_en_fecha`: cantidad de mudanzas activas
    (CONFIRMADA o EN_CURSO) asignadas al empleado en la fecha dada.
    Un único hit a la BD independientemente del número de empleados.
    """
    return (
        Empleado.objects.annotate(
            mudanzas_en_fecha=Count(
                "asignaciones",
                filter=Q(
                    asignaciones__mudanza__estado__in=[
                        Mudanza.Estado.CONFIRMADA,
                        Mudanza.Estado.EN_CURSO,
                    ],
                    asignaciones__mudanza__fecha_hora__date=fecha,
                ),
            )
        ).order_by("nombre")
    )

def _aplicar_filtros(qs: QuerySet, filtros: FiltrosEmpleado) -> QuerySet:
    if filtros.q.strip():
        termino = filtros.q.strip()
        qs = qs.filter(
            Q(nombre__icontains=termino)
            | Q(dni__icontains=termino)
            | Q(nro_licencia__icontains=termino)
        )
    if filtros.rol and filtros.rol in Empleado.Rol.values:
        qs = qs.filter(rol=filtros.rol)
    if filtros.solo_disponibles:
        qs = qs.filter(disponible=True)
    return qs


def _paginar(qs: QuerySet, page: int, page_size: int) -> QuerySet:
    offset = (max(1, page) - 1) * page_size
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

# API pública del servicio

def obtener_empleados_listado(
    filtros: FiltrosEmpleado,
    fecha: date | None = None,
) -> dict:
    """
    Retorna el contexto completo para la vista de listado de empleados.

    `fecha` determina contra qué día se evalúa la disponibilidad.
    Si es None se usa `hoy`.
    """
    hoy = fecha or timezone.localdate()

    qs = _qs_base(hoy)
    qs = _aplicar_filtros(qs, filtros)

    total = qs.count()
    pagina = _paginar(qs, filtros.page, filtros.page_size)

    empleados = [_serializar_empleado(emp, hoy) for emp in pagina]

    # Resumen de alertas para el header de la vista
    total_con_alerta = sum(1 for e in empleados if e["tiene_alerta_documental"])

    return {
        "empleados": empleados,
        "paginacion": _construir_paginacion(total, filtros.page, filtros.page_size),
        "filtros_activos": {"q": filtros.q, "rol": filtros.rol},
        "opciones_rol": _opciones_rol(),
        "fecha_consulta_iso": hoy.isoformat(),
        "resumen_alertas": {
            "total_con_alerta": total_con_alerta,
            "hay_alertas": total_con_alerta > 0,
        },
    }

def validar_disponibilidad_para_fecha(empleado_id: int, fecha: date) -> dict:
    """
    Valida un empleado puntual para una fecha dada.
    Útil para APIs de asignación (ej: al crear/editar una mudanza).

    Raises: Empleado.DoesNotExist si el id no existe.
    """
    emp = _qs_base(fecha).get(pk=empleado_id)
    hoy = timezone.localdate()

    serializado = _serializar_empleado(emp, hoy)

    # Bloqueo duro: no debe asignarse si tiene documentación vencida o no está disponible
    bloqueado = (
        not emp.disponible
        or serializado["disponibilidad_valor"] == "ocupado"
        or (emp.rol == Empleado.Rol.CONDUCTOR and serializado["alerta_licencia"]
            and emp.licencia_fecha_vencimiento is not None
            and emp.licencia_fecha_vencimiento < fecha)
    )

    return {
        **serializado,
        "puede_asignarse": not bloqueado,
        "motivo_bloqueo": _motivo_bloqueo(serializado, emp, fecha) if bloqueado else None,
    }

def _motivo_bloqueo(serializado: dict, emp: Empleado, fecha: date) -> str:
    if not emp.disponible:
        return "Empleado marcado como no disponible."
    if serializado["disponibilidad_valor"] == "ocupado":
        return f"Ya tiene una mudanza asignada el {fecha.strftime('%d/%m/%Y')}."
    if emp.rol == Empleado.Rol.CONDUCTOR and emp.licencia_fecha_vencimiento and emp.licencia_fecha_vencimiento < fecha:
        return f"Licencia vencida el {emp.licencia_fecha_vencimiento.strftime('%d/%m/%Y')}."
    return "No puede asignarse."


def _opciones_rol() -> list[dict]:
    return [{"valor": r.value, "label": r.label} for r in Empleado.Rol]