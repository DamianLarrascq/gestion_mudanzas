from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, get_object_or_404
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from gestion.services.dashboard_service import (
    obtener_actividad_reciente,
    obtener_kpis,
    obtener_mudanzas_hoy
)
from gestion.services.mudanzas_list_service import  FiltrosMudanza, obtener_mudanzas_filtradas
from gestion.models.clientes import Cliente
from gestion.services.clientes_service import (
FiltrosCliente, obtener_clientes_filtrados, obtener_detalle_cliente
)

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