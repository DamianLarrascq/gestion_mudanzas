from django.db import models


class Cliente(models.Model):
    nombre_completo = models.CharField(max_length=200)
    dni = models.CharField(max_length=15, unique=True, blank=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    telefono = models.CharField(max_length=20, unique=True)
    email = models.EmailField(blank=True, null=True, unique=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'
        ordering = ['-creado_en']

    def __str__(self):
        return f'{self.nombre_completo} ({self.telefono})'
