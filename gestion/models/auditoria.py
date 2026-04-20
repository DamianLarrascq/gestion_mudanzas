from django.contrib.auth.models import User
from django.db import models
from .mudanzas import Mudanza


class HistorialEstado(models.Model):
    mudanza = models.ForeignKey(Mudanza, on_delete=models.CASCADE, related_name='historial_estados')
    estado_anterior = models.CharField(max_length=20, choices=Mudanza.Estado.choices)
    estado_nuevo = models.CharField(max_length=20, choices=Mudanza.Estado.choices)
    usuario = models.ForeignKey(User, on_delete=models.PROTECT, related_name='cambios_estado')
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Historial de estado'
        verbose_name_plural = 'Historial de estados'
        ordering = ['-fecha']

    def __str__(self):
        return (
            f'Mudanza #{self.mudanza_id}: '
            f'{self.estado_anterior} → {self.estado_nuevo}'
        )