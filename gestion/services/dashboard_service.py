from datetime import date, timedelta
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone
from gestion.models.mudanzas import Mudanza
from gestion.models.auditoria import HistorialEstado
from gestion.models.flota import Empleado
from gestion.models.presupuestos import Presupuesto

# Constantes de UI

ESTADO_BADGE: dict[str, str] = {
    Mudanza.Estado.BORRADOR: 'badge-secondary',
    Mudanza.Estado.PRESUPUESTADA: 'badge-info',
    Mudanza.Estado.CONFIRMADA: 'badge-primary',
    Mudanza.Estado.EN_CURSO: 'badge-warning',
    Mudanza.Estado.COMPLETADA: 'badge-success',
    Mudanza.Estado.CANCELADA: 'badge-danger',
    Mudanza.Estado.POSPUESTA: 'badge-dark',
}

ESTADO_LABEL = dict(Mudanza.Estado.choices)

# KPIs

def _calcular_ingresos_mes(hoy: date) -> dict:
    """
    Retorna total cobrado (presupuesto de mudanzas completas)
    en el mes actual vs el mes anterior para calcular trend.
    """
    primer_dia_mes = hoy.replace(day=1)
    primer_dia_mes_anterior = (primer_dia_mes - timedelta(days=1)).replace(day=1)

    def total_mes(desde: date, hasta: date) -> Decimal:
        return (
            Presupuesto.objects.filter(
                mudanza__estado = Mudanza.Estado.COMPLETADA,
                mudanza__fecha_hora__date__gte=desde,
                mudanza__fecha_hora__date__lt=hasta,
            ).aggregate(total=Sum('total'))['total'] or Decimal('0')
        )

    mes_actual = total_mes(primer_dia_mes, hoy + timedelta(days=1))
    mes_anterior = total_mes(primer_dia_mes_anterior, primer_dia_mes)

    if mes_anterior > 0:
        variacion = ((mes_actual - mes_anterior) / mes_anterior * 100).quantize(Decimal('1'))
        trend_label = f"{'+' if variacion >=0 else ''}{variacion}% vs mes anterior"
        trend_positivo = variacion >= 0
    else:
        trend_label = 'Sin dato de mes anterior'
        trend_positivo = True

    return {
        'valor_raw': mes_actual,
        'trend_label': trend_label,
        'trend_positivo': trend_positivo,
    }

def _calcular_mudanzas_activas() -> dict:
    """
    Mudanzas confirmadas + en curso. Trend: comprar con hace 7 dias.
    """
    estados_activos = [Mudanza.Estado.CONFIRMADA, Mudanza.Estado.EN_CURSO]

    activas_ahora = Mudanza.objects.filter(estado__in=estados_activos).count()

    hace_7_dias = timezone.now() - timedelta(days=7)
    activas_semana_pasada = (
        Mudanza.objects.filter(
            estado__in = estados_activos,
            creado_en__lte = hace_7_dias,
        ).count()
    )

    delta = activas_ahora - activas_semana_pasada
    trend_label = f"{'+' if delta >= 0 else ''}{delta} vs semana pasada"
    trend_positivo = delta >= 0

    return {
        'valor_raw': activas_ahora,
        'trend_label': trend_label,
        'trend_positivo': trend_positivo,
    }

def _calcular_empleados_disponibles_hoy(hoy: date) -> dict:
    """
    Empleados marcados como disponibles que no tienen una asignacion en una mudanza en curso hoy.
    """
    total_disponibles = Empleado.objects.filter(disponible=True).count()

    ocupados_hoy = (
        Empleado.objects.filter(
            asignaciones__mudanza__estado=Mudanza.Estado.EN_CURSO,
            asignaciones__mudanza__fecha_hora__date=hoy,
        ).distinct().count()
    )

    libres = total_disponibles - ocupados_hoy

    return {
        'valor_raw': libres,
        'subtitulo': f"{ocupados_hoy} en servicio hoy",
        'trend_label': f'{total_disponibles} disponibles en total',
        'trend_positivo': libres > 0,
    }

def obtener_kpis(hoy: date | None = None) -> list[dict]:
    """
    Retorna lista de KPI cards listas para renderizar.
    Cada item tiene: label, value, icon, trend_label, trend_positivo, subtitulo.
    """
    hoy = hoy or timezone.localdate()
    ingresos = _calcular_ingresos_mes(hoy)
    activas = _calcular_mudanzas_activas()
    empleados = _calcular_empleados_disponibles_hoy(hoy)

    # Mudanzas completadas este mes
    completadas_mes = Mudanza.objects.filter(
        estado=Mudanza.Estado.COMPLETADA,
        fecha_hora__date__gte=hoy.replace(day=1),
    ).count()

    return [
        {
            'label': 'Ingresos del mes',
            'value': f"${ingresos['valor_raw']:,.0f}",
            'icon': 'currency-dollar',
            'trend_label': ingresos["trend_label"],
            'trend_positivo': ingresos['trend_positivo'],
            'subtitulo': None,
        },
        {
            'label': 'Mudanzas activas',
            'value': str(activas['valor_raw']),
            'icon': 'truck',
            'trend_label': activas['trend_label'],
            'trend_positivo': activas['trend_positivo'],
            'subtitulo': None,
        },
        {
            'label': 'Empleados disponibles',
            'value': str(empleados['valor_raw']),
            'icon': 'users',
            'trend_label': empleados["trend_label"],
            'trend_positivo': empleados['trend_positivo'],
            'subtitulo': empleados['subtitulo'],
        },
        {
            'label': 'Completadas este mes',
            'value': str(completadas_mes),
            'icon': 'check-circle',
            'trend_label': None,
            'trend_positivo': True,
            'subtitulo': None,
        },
    ]

# Mudanzas de hoy

def obtener_mudanzas_hoy(hoy: date | None = None) -> list[dict]:
    """
    Retorna las mudanzas del dia con datos ya formateados para la tabla.
    Ordenadas por fecha_hora ascendente
    """
    hoy = hoy or timezone.localdate()

    qs = (
        Mudanza.objects.filter(fecha_hora__date=hoy).exclude(estado=Mudanza.Estado.CANCELADA).select_related('cliente', 'origen', 'destino', 'camion').order_by('fecha_hora')
    )

    resultado = []
    for m in qs:
        estado_key = m.estado
        resultado.append({
            'id': m.pk,
            'uuid': str(m.uuid),
            'cliente_nombre': m.cliente.nombre_completo,
            'cliente_tel': m.cliente.telefono,
            'hora': timezone.localtime(m.fecha_hora).strftime('%H:%M'),
            'origen': f"{m.origen.calle} {m.origen.numero}, {m.origen.localidad}" if m.origen else "-",
            "destino": f"{m.destino.calle} {m.destino.numero}, {m.destino.localidad}" if m.destino else "—",
            "estado_label": ESTADO_LABEL[estado_key],
            "estado_badge": ESTADO_BADGE[estado_key],
            "camion_patente": m.camion.patente if m.camion else "Sin asignar",
            "senia_pagada": m.senia_pagada,
            "url_detalle": f"/gestion/mudanzas/{m.pk}/",
        })

    return resultado

# Actividad reciente

def obtener_actividad_reciente(limite: int = 5) -> list[dict]:
    """
    Ultimos N eventos de HistorialEstado.
    Retorna datos listos para un feed de actividad.
    """

    qs = (
        HistorialEstado.objects.select_related('mudanza', 'usuario').order_by("-fecha")[:limite]
    )

    resultado = []
    for evento in qs:
        resultado.append({
            "mudanza_id": evento.mudanza_id,
            "mudanza_url": f"/gestion/mudanzas/{evento.mudanza_id}/",
            "estado_anterior": ESTADO_LABEL.get(evento.estado_anterior, evento.estado_anterior),
            "estado_nuevo": ESTADO_LABEL.get(evento.estado_nuevo, evento.estado_nuevo),
            "estado_nuevo_badge": ESTADO_BADGE.get(evento.estado_nuevo, "badge-secondary"),
            "usuario_nombre": evento.usuario.get_full_name() or evento.usuario.username,
            "fecha_iso": evento.fecha.isoformat(),
            "fecha_humanizada": _humanizar_fecha(evento.fecha),
        })

    return resultado

def _humanizar_fecha(dt) -> str:
    ahora = timezone.now()
    delta = ahora - dt
    minutos = int(delta.total_seconds() // 60)

    if minutos < 1:
        return "Ahora mismo"
    if minutos < 60:
        return f"hace {minutos} min."
    horas = minutos // 60
    if horas < 24:
        return f'Hace {horas} h'
    dias = horas // 24
    return f'Hace {dias} d'