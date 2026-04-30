from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from gestion.services.dashboard_service import (
    obtener_actividad_reciente,
    obtener_kpis,
    obtener_mudanzas_hoy
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