from django.urls import path
from gestion import views
from gestion.views import MudanzaCreateView

app_name = 'gestion'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Mudanzas
    path('mudanzas/', views.MudanzaListView.as_view(), name='mudanza_list'),
    path('mudanzas/<int:pk>/resumen/', views.ResumenMudanzaView.as_view(), name='mudanza_resumen'),
    path('mudanzas/nueva/', MudanzaCreateView.as_view(), name='mudanza_nueva'),

    # Clientes
    path('clientes/', views.ClienteListView.as_view(), name='cliente_list'),
    path('clientes/<int:pk>/', views.ClienteDetailView.as_view(), name='cliente_detail'),

    # Empleados
    path('empleados/', views.EmpleadoListView.as_view(), name='empleado_list'),
    path('empleados/nuevo/', views.EmpleadoCreateView.as_view(), name='empleado_create'),
    path('empleados/<int:pk>/', views.EmpleadoDetailView.as_view(), name='empleado_detail'),
    path('empleados/<int:pk>/editar/', views.EmpleadoUpdateView.as_view(), name='empleado_update'),
    path('empleados/<int:pk>/borrar/', views.empleado_delete, name='empleado_delete'),
    path('empleados/<int:empleado_id>/disponibilidad/', views.api_validar_disponibilidad, name='api_empleado_disponibilidad'),

    # Flota
    path('flota/', views.FlotaMonitorView.as_view(), name='flota_monitor'),

    # Configuración de tarifas
    path('configuracion/tarifas/', views.ConfiguracionTarifaView.as_view(), name='config_tarifas'),
    path('configuracion/tarifas/nueva/', views.TarifaCreateView.as_view(), name='tarifa_create'),
    path('configuracion/tarifas/<int:pk>/editar/', views.TarifaUpdateView.as_view(), name='tarifa_update'),

    # APIs internas
    path('mudanzas/<int:mudanza_id>/validar-capacidad/', views.api_validar_capacidad_camion, name='api_validar_capacidad'),
]