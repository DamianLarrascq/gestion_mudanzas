from django.db import models
from django.forms import ValidationError
from .clientes import Cliente
from .flota import Camion, Empleado
from datetime import timedelta


class Mudanza(models.Model):
    class Estado(models.TextChoices):
        BORRADOR = 'BORRADOR', 'Borrador'
        PRESUPUESTADA = 'PRESUPUESTADA', 'Presupuestada'
        CONFIRMADA = 'CONFIRMADA', 'Confirmada (seña pagada)'
        EN_CURSO = 'EN_CURSO', 'En curso'
        COMPLETADA = 'COMPLETADA', 'Completada'
        CANCELADA = 'CANCELADA', 'Cancelada'
        POSPUESTA = 'POSPUESTA', 'Pospuesta'

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='mudanzas')
    camion = models.ForeignKey(Camion, null=True, blank=True, on_delete=models.SET_NULL, related_name='mudanzas')
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.BORRADOR)
    fecha_hora = models.DateTimeField()
    domicilio_origen = models.CharField(max_length=300)
    domicilio_destino = models.CharField(max_length=300)
    lat_origen        = models.FloatField(null=True, blank=True)
    lng_origen        = models.FloatField(null=True, blank=True)
    lat_destino       = models.FloatField(null=True, blank=True)
    lng_destino       = models.FloatField(null=True, blank=True)
    piso_origen       = models.PositiveSmallIntegerField(default=0)
    ascensor_origen   = models.BooleanField(default=False)
    piso_destino      = models.PositiveSmallIntegerField(default=0)
    ascensor_destino  = models.BooleanField(default=False)
    distancia_km      = models.DecimalField(max_digits=8, decimal_places=2,
                            null=True, blank=True)
    necesita_ayudantes = models.BooleanField(default=True)
    monto_senia       = models.DecimalField(max_digits=10, decimal_places=2,
                            null=True, blank=True)
    senia_pagada      = models.BooleanField(default=False)
    mp_preference_id  = models.CharField(max_length=200, blank=True)
    creado_en         = models.DateTimeField(auto_now_add=True)
    actualizado_en    = models.DateTimeField(auto_now=True)  

    def get_rango_horario(self):
        fin = self.fecha_hora + timedelta(hours=2)
        return self.fecha_hora, fin

    def clean(self):
        if not self.fecha_hora:
            return

        inicio, fin = self.get_rango_horario()

        if self.camion:
            conflicto_camion = Mudanza.objects.filter(
                camion=self.camion,
                fecha_hora__lt=fin,
                fecha_hora__gt=inicio - timedelta(hours=2),
                estado__in=[
                    self.Estado.CONFIRMADA,
                    self.Estado.EN_CURSO,
                ],
            ).exclude(pk=self.pk)

            if conflicto_camion.exists():
                raise ValidationError({
                    'camion': f'El camión {self.camion} ya tiene una mudanza asignada en ese horario.'
                })


    class Meta:
        verbose_name = 'Mudanza'
        verbose_name_plural = 'Mudanzas'
        ordering = ['-fecha_hora']

    def __str__(self):
        return f'Mudanza #{self.pk}'


class AsignacionEmpleado(models.Model):
    mudanza = models.ForeignKey(Mudanza, on_delete=models.CASCADE, related_name='asignaciones')
    empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT, related_name='asignaciones')
    rol = models.CharField(max_length=20, choices=Empleado.Rol.choices)

    class Meta:
        unique_together = [['mudanza', 'empleado']]
        verbose_name = 'Asignación de empleado'
        verbose_name_plural = 'Asignaciones de empleados'

    def __str__(self):
        return f'{self.empleado} en Mudanza #{self.mudanza.id}'

    
class ItemInventario(models.Model):
    class Tipo(models.TextChoices):
        HELADERA   = "HELADERA",   "Heladera"
        LAVARROPAS = "LAVARROPAS", "Lavarropas"
        CAMA       = "CAMA",       "Cama"
        SOFA       = "SOFA",       "Sofá"
        MESA       = "MESA",       "Mesa comedor"
        PLACARD    = "PLACARD",    "Placard / Ropero"
        CAJA       = "CAJA",       "Caja / Bulto"
        OTRO       = "OTRO",       "Otro"

    mudanza     = models.ForeignKey(Mudanza, on_delete=models.CASCADE,
                      related_name="inventario")
    tipo        = models.CharField(max_length=20, choices=Tipo.choices)
    descripcion = models.CharField(max_length=200, blank=True)
    cantidad    = models.PositiveSmallIntegerField(default=1)

    class Meta:
        verbose_name        = "Ítem de inventario"
        verbose_name_plural = "Ítems de inventario"

    def __str__(self):
        return f"{self.cantidad}x {self.get_tipo_display()}"
