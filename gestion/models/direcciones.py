from django.db import models


class Direccion(models.Model):
    calle = models.CharField(max_length=200)
    numero = models.CharField(max_length=10)
    piso = models.PositiveSmallIntegerField(default=0)
    departamento = models.CharField(max_length=10, blank=True, null=True)
    localidad = models.CharField(max_length=100)
    provincia = models.CharField(max_length=100)
    codigo_postal = models.CharField(max_length=15)
    latitud = models.FloatField(null=True, blank=True)
    longitud = models.FloatField(null=True, blank=True)
    tiene_ascensor = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Dirección'
        verbose_name_plural = 'Direcciones'

    def __str__(self):
        return f'{self.calle} {self.altura}, {self.localidad}'
