from django.db import models
from .mudanzas import Mudanza


class FotoInventario(models.Model):
    class Momento(models.TextChoices):
        CARGA = 'CARGA', 'Carga'
        DESCARGA = 'DESCARGA', 'Descarga'

    mudanza = models.ForeignKey(Mudanza, on_delete=models.CASCADE, related_name='fotos')
    momento = models.CharField(max_length=10, choices=Momento.choices)
    imagen = models.ImageField(upload_to='inventario/%Y/%m/')
    subida_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Foto de inventario'
        verbose_name_plural = 'Fotos de inventario'
        ordering = ['momento', 'subida_en']

    def __str__(self):
        return f'{self.get_momento_display()} - Mudanza #{self.mudanza_id}'