from django.db import models
from django.contrib.auth.models import User


class Camion(models.Model):
    class Categoria(models.TextChoices):
        N1 = 'N1', 'Liviano N1 (2.5-3.5 t)'
        N2 = 'N2', 'Mediano N2 (4.5-5.5 t)'

    patente = models.CharField(max_length=10, unique=True)
    modelo = models.CharField(max_length=100)
    categoria = models.CharField(max_length=2, choices=Categoria.choices)
    activo = models.BooleanField(default=True)
    capacidad_volumen_m3 = models.DecimalField(max_digits=6, decimal_places=2, help_text='Volumen máximo')
    capacidad_peso_kg = models.DecimalField(max_digits=8, decimal_places=2, help_text='Peso máximo')
    anio = models.PositiveSmallIntegerField(default=0)
    vtv_fecha_vencimiento = models.DateField(null=True, blank=True)
    seguro_fecha_vencimiento = models.DateField(null=True, blank=True)
    patente_fecha_vencimiento = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = 'Camión'
        verbose_name_plural = 'Camiones'

    def __str__(self):
        return f'{self.patente} - {self.categoria}'


class Empleado(models.Model):
    class Rol(models.TextChoices):
        CONDUCTOR = 'CONDUCTOR', 'Conductor'
        AYUDANTE = 'AYUDANTE', 'Ayudante de carga'
        ADMIN = 'ADMIN', 'Administrativo'

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='empleado')
    nombre = models.CharField(max_length=200)
    dni = models.CharField(max_length=15, unique=True)
    rol = models.CharField(max_length=20, choices=Rol.choices)
    nro_licencia = models.CharField(max_length=50, blank=True, unique=True)
    licencia_fecha_vencimiento = models.DateField(null=True, blank=True)
    disponible = models.BooleanField(default=True)
    art = models.BooleanField(default=True)
    seguro_riesgo = models.DateField(null=True, blank=True)
    seguro_ayudante_carga = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = 'Empleado'
        verbose_name_plural = 'Empleados'

    def __str__(self):
        return f'{self.nombre} - {self.categoria}'
