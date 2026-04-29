from django.db import models


class Direccion(models.Model):
    calle = models.CharField(max_length=200)
    numero = models.CharField(max_length=10)
    piso = models.CharField(max_length=10, default="PB")
    capacidad_ascensor_kg = models.PositiveIntegerField(null=True, blank=True)
    ascensor_grande = models.BooleanField(default=False, help_text="¿Entra un colchón/sofá?")
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
