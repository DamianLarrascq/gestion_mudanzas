from gestion.models import Notificacion

def notificaciones(request):
    return {
        "cantidad_notificaciones": Notificacion.objects.count(),
        "ultimas_notificaciones": (
            Notificacion.objects.order_by("-id")[:5]
        )
    }