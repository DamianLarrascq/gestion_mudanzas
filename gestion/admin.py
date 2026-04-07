from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import (
    Cliente,
    Camion,
    Empleado,
    Mudanza,
    AsignacionEmpleado,
    ItemInventario,
    TarifaBase,
    Presupuesto,
    Notificacion,
)

@admin.register(Cliente)
class ClienteAdmin(ModelAdmin):
    list_display = ['nombre_completo', 'telefono', 'email', 'creado_en']
    search_fields = ['nombre_completo', 'telefono', 'email']


@admin.register(Camion)
class CamionAdmin(ModelAdmin):
    list_display = ['patente', 'modelo', 'categoria', 'capacidad_ton', 'activo']
    list_filter = ['categoria', 'activo']


@admin.register(Empleado)
class EmpleadoAdmin(ModelAdmin):
    list_display = ['__str__', 'rol', 'disponible']
    list_filter = ['rol', 'disponible']


@admin.register(Mudanza)
class MudanzaAdmin(ModelAdmin):
    list_display = ['__str__', 'cliente', 'fecha_hora', 'estado', 'camion']
    list_filter = ['estado']
    search_fields = ['cliente__nombre_completo', 'domicilio_origen', 'domicilio_destino']


@admin.register(TarifaBase)
class TarifaBaseAdmin(ModelAdmin):
    list_display = ['nombre', 'precio_por_km', 'precio_ayudante', 'activa', 'vigente_desde']


@admin.register(Presupuesto)
class PresupuestoAdmin(ModelAdmin):
    list_display = ['mudanza', 'total', 'calculado_en']


@admin.register(Notificacion)
class NotificacionAdmin(ModelAdmin):
    list_display = ['mudanza', 'tipo', 'canal', 'enviada', 'enviada_en']
    list_filter = ['tipo', 'canal', 'enviada']
