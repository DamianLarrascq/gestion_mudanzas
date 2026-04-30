from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from gestion.services.dashboard_service import (
    obtener_actividad_reciente,
    obtener_kpis,
    obtener_mudanzas_hoy
)
from gestion.services.mudanzas_list_service import  FiltrosMudanza, obtener_mudanzas_filtradas

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