from django.db import models


class CatalogoItem(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    volumen_m3 = models.DecimalField(max_digits=6, decimal_places=3)
    peso_estimado_kg = models.DecimalField(max_digits=7, decimal_places=2)

    class Meta:
        verbose_name = 'Ítem de catálogo'
        verbose_name_plural = 'Ítems de catálogo'
        ordering = ['nombre']

    def __str__(self):
        return f'{self.nombre} ({self.volumen_m3} m³)'