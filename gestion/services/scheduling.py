from datetime import timedelta
from django.core.exceptions import ValidationError
from gestion.models import Mudanza, AsignacionEmpleado, Camion, Empleado

DURACION_MUDANZA_HS = 2

def get_rango_horario(fecha_hora):
    return fecha_hora, fecha_hora + timedelta(hours=DURACION_MUDANZA_HS)

def verificar_disponibilidad_camion(camion: Camion, fecha_hora, exclude_mudanza_id=None):
    inicio, fin = get_rango_horario(fecha_hora)

    qs = Mudanza.objects.filter(
        camion=camion,
        fecha_hora__lt=fin,
        fecha_hora__gt=inicio - timedelta(hours=DURACION_MUDANZA_HS),
        estado__in=[Mudanza.Estado.CONFIRMADA, Mudanza.Estado.EN_CURSO],
    )

    if exclude_mudanza_id:
        qs = qs.exclude(pk=exclude_mudanza_id)

    if qs.exists():
        raise ValidationError(
            f'El camión {camion} ya tiene una mudanza asignada en ese horario.'
        )

def verificar_disponibilidad_empleado(empleado: Empleado, fecha_hora, exclude_mudanza_id=None):
    inicio, fin = get_rango_horario(fecha_hora)

    qs = AsignacionEmpleado.objects.filter(
        empleado = empleado,
        mudanza__fecha_hora__lt=fin,
        mudanza__fecha_hora__gt=inicio - timedelta(hours=DURACION_MUDANZA_HS),
        mudanza__estado__in=[
            Mudanza.Estado.CONFIRMADA,
            Mudanza.Estado.EN_CURSO,
            Mudanza.Estado.PRESUPUESTADA,
        ],
    )

    if exclude_mudanza_id:
        qs = qs.exclude(mudanza_id=exclude_mudanza_id)

    if qs.exists():
        conflicto = qs.select_related('mudanza').first()
        raise ValidationError(
            f'{empleado.nombre} ya está asignado a la mudanza '
            f'#{conflicto.mudanza_id} en ese horario.'
        )