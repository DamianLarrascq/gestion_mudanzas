from django.db import models
from .clientes import Cliente
from .flota import Camion, Empleado
from .catalogo import CatalogoItem
from .direcciones import Direccion
import uuid


class Mudanza(models.Model):
    class Estado(models.TextChoices):
        BORRADOR = 'BORRADOR', 'Borrador'
        PRESUPUESTADA = 'PRESUPUESTADA', 'Presupuestada'
        CONFIRMADA = 'CONFIRMADA', 'Confirmada (seña pagada)'
        EN_CURSO = 'EN_CURSO', 'En curso'
        COMPLETADA = 'COMPLETADA', 'Completada'
        CANCELADA = 'CANCELADA', 'Cancelada'
        POSPUESTA = 'POSPUESTA', 'Pospuesta'

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='mudanzas')
    camion = models.ForeignKey(Camion, null=True, blank=True, on_delete=models.SET_NULL, related_name='mudanzas')
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.BORRADOR)
    fecha_hora = models.DateTimeField()
    origen = models.ForeignKey(Direccion, null=True, blank=True, on_delete=models.PROTECT, related_name='mudanzas_como_origen')
    destino = models.ForeignKey(Direccion, null=True, blank=True, on_delete=models.PROTECT, related_name='mudanzas_como_destino')
    distancia_km = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    necesita_ayudantes = models.BooleanField(default=True)
    monto_senia       = models.DecimalField(max_digits=10, decimal_places=2,
                            null=True, blank=True)
    senia_pagada      = models.BooleanField(default=False)
    mp_preference_id  = models.CharField(max_length=200, blank=True)
    creado_en         = models.DateTimeField(auto_now_add=True)
    actualizado_en    = models.DateTimeField(auto_now=True)  

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
    mudanza = models.ForeignKey(Mudanza, on_delete=models.CASCADE, related_name='inventario')
    cantidad = models.PositiveSmallIntegerField(default=1)
    descripcion = models.CharField(max_length=200, blank=True)
    catalogo_item = models.ForeignKey(CatalogoItem, null=True, blank=True, on_delete=models.SET_NULL, related_name='items_inventario')

    class Meta:
        verbose_name        = "Ítem de inventario"
        verbose_name_plural = "Ítems de inventario"
