"""
Mixins de autorización para las vistas del panel de gestión.

Jerarquía de acceso:
    - StaffRequiredMixin solo is_staff=True (admin, administrativo)
    - MudanzaOwnerMixin is_staff OR conductor/ayudante asignado a esa mudanza
"""
from __future__ import annotations
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import user_passes_test
from gestion.models.mudanzas import Mudanza

staff_required = user_passes_test(
    lambda u: u.is_staff,
    login_url='/gestion/login/'
)


class StaffRequiredMixin(LoginRequiredMixin):
    """
    Restringe el acceso a usuarios con is_staff=True.

    Aplicar a vistas que gestionan recursos globales de la empresa (clientes, empleados, tarifas, flota) donde no existe una relacion de propiedad individual con el usuario autenticado.

    Raises:
        PermissionDenied (HTTP 403) si el usuario esta autenticado pero no es staff.
    """

    def dispatch(self, request, *args, **kwargs):
        # LoginRequiredMixin redirige a login si no esta autenticado.
        response = super().dispatch(request, *args, **kwargs)
        # Si super() ya redirigio (no autenticado), respetar esa respuesta
        if not request.user.is_authenticated:
            return response
        if not request.user.is_staff:
            raise PermissionDenied
        return response


class MudanzaOwnerMixin(LoginRequiredMixin):
    """
    Permite acceso a una Mudanza si el usuario es staff o esta asignado a ella.

    Diseñado para ResumenMudanzaView y cualquier vista de detalle de Mudanza que deba ser accesible también por conductores/ayudantes asignados.

    Asume que la URL contiene 'pk' como identificador de la Mudanza.

    Raises:
        PermissionDenied (HTTP 403) si el usuario no tiene relación con la mudanza solicitada.
    """

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if not request.user.is_authenticated:
            return response

        # staff ve todo
        if request.user.is_staff:
            return response

        # Empleados no-staff: verificar asignacion
        mudanza_pk = kwargs.get('pk')
        if mudanza_pk is None:
            raise PermissionDenied

        empleado_asignado = (
            Mudanza.objects.filter(
                pk=mudanza_pk,
                asignaciones__empleado__user=request.user,
            ).exists()
        )
        if not empleado_asignado:
            raise PermissionDenied

        return response
