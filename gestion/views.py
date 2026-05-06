from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from gestion.models import Empleado
from gestion.services.dashboard_service import (
    obtener_actividad_reciente,
    obtener_kpis,
    obtener_mudanzas_hoy
)
from gestion.services.empleados_service import FiltrosEmpleado, obtener_empleados_listado, \
    validar_disponibilidad_para_fecha
from gestion.services.flota_service import obtener_estado_flota
from gestion.services.mudanzas_list_service import FiltrosMudanza, obtener_mudanzas_filtradas
from gestion.models.clientes import Cliente
from gestion.services.clientes_service import (
    FiltrosCliente, obtener_clientes_filtrados, obtener_detalle_cliente
)
import datetime


@login_required
def dashboard(request):
    hoy = timezone.localdate()

    context = {
        'titulo_pagina': 'Dashboard',
        'seccion_activa': 'dashboard',
        'fecha_activa': hoy.strftime('%-d de %B de %Y'),

        'kpis': obtener_kpis(hoy),
        'mudanzas_hoy': obtener_mudanzas_hoy(hoy),
        'actividad_reciente': obtener_actividad_reciente(limite=5)
    }

    return render(request, 'gestion/dashboard.html', context)


# Mudanzas

class MudanzaListView(LoginRequiredMixin, TemplateView):
    template_name = 'gestion/mudanzas/lista.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        filtros = FiltrosMudanza(
            q=self.request.GET.get('q', '').strip(),
            estado=self.request.GET.get('estado', '').strip(),
            page=self._parse_page(),
            page_size=20,
        )

        ctx.update(obtener_mudanzas_filtradas(filtros))
        ctx['titulo_pagina'] = 'Mudanzas'
        ctx['seccion_activa'] = 'mudanzas'
        return ctx

    def _parse_page(self) -> int:
        try:
            page = int(self.request.GET.get('page', 1))
            return max(1, page)
        except (ValueError, TypeError):
            return 1


# Clientes

class ClienteListView(LoginRequiredMixin, TemplateView):
    template_name = 'gestion/clientes/lista.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        filtros = FiltrosCliente(
            q=self.request.GET.get('q', '').strip(),
            segmento=self.request.GET.get('segmento', '').strip(),
            page=self._parse_page(),
            page_size=25,
        )

        ctx.update(obtener_clientes_filtrados(filtros))
        ctx['titulo_pagina'] = 'Clientes'
        ctx['seccion_activa'] = 'clientes'
        return ctx

    def _parse_page(self) -> int:
        try:
            return max(1, int(self.request.GET.get('page', 1)))
        except (ValueError, TypeError):
            return 1


class ClienteDetailView(LoginRequiredMixin, TemplateView):
    template_name = "gestion/clientes/detalle.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # Valida existencia antes de pasar al service
        get_object_or_404(Cliente, pk=self.kwargs["pk"])

        ctx.update(obtener_detalle_cliente(self.kwargs["pk"]))
        ctx["titulo_pagina"] = "Detalle de cliente"
        ctx["seccion_activa"] = "clientes"
        return ctx


# Empleados

class EmpleadoListView(LoginRequiredMixin, TemplateView):
    template_name = "gestion/empleados/lista.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # Fecha de consulta: permite evaluar disponibilidad para otro día
        fecha = self._parse_fecha()

        filtros = FiltrosEmpleado(
            q=self.request.GET.get("q", "").strip(),
            rol=self.request.GET.get("rol", "").strip(),
            solo_disponibles=self.request.GET.get("solo_disponibles") == "1",
            page=self._parse_page(),
            page_size=25,
        )

        ctx.update(obtener_empleados_listado(filtros, fecha))
        ctx["titulo_pagina"] = "Empleados"
        ctx["seccion_activa"] = "empleados"
        return ctx

    def _parse_page(self) -> int:
        try:
            return max(1, int(self.request.GET.get("page", 1)))
        except (ValueError, TypeError):
            return 1

    def _parse_fecha(self) -> datetime.date | None:
        raw = self.request.GET.get("fecha", "").strip()
        if not raw:
            return None
        try:
            return datetime.date.fromisoformat(raw)
        except ValueError:
            return None


@login_required
def api_validar_disponibilidad(request, empleado_id: int):
    """
    GET /gestion/empleados/<id>/disponibilidad/?fecha=YYYY-MM-DD
    Retorna JSON con disponibilidad y alertas para usar en modales de asignación.
    """
    raw_fecha = request.GET.get("fecha", "").strip()
    try:
        fecha = datetime.date.fromisoformat(raw_fecha) if raw_fecha else timezone.localdate()
    except ValueError:
        return JsonResponse({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)

    try:
        resultado = validar_disponibilidad_para_fecha(empleado_id, fecha)
    except Empleado.DoesNotExist:
        return JsonResponse({"error": "Empleado no encontrado."}, status=404)

    return JsonResponse(resultado)


# Flota

class FlotaMonitorView(LoginRequiredMixin, TemplateView):
    template_name = "gestion/flota/monitor.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(obtener_estado_flota())
        ctx["titulo_pagina"] = "Monitoreo de Flota"
        ctx["seccion_activa"] = "flota"
        return ctx
