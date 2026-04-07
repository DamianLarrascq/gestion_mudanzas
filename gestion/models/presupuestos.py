from django.db import models
from .mudanzas import Mudanza


class TarifaBase(models.Model):
    nombre          = models.CharField(max_length=100)
    precio_por_km   = models.DecimalField(max_digits=8, decimal_places=2)
    precio_ayudante = models.DecimalField(max_digits=8, decimal_places=2,
                          help_text="Precio por ayudante por mudanza")
    recargo_piso    = models.DecimalField(max_digits=8, decimal_places=2,
                          help_text="Recargo por piso sin ascensor")
    activa          = models.BooleanField(default=True)
    vigente_desde   = models.DateField()

    class Meta:
        verbose_name        = "Tarifa base"
        verbose_name_plural = "Tarifas base"
        ordering            = ["-vigente_desde"]

    def __str__(self):
        return f"{self.nombre} (desde {self.vigente_desde})"


class Presupuesto(models.Model):
    mudanza         = models.OneToOneField(Mudanza, on_delete=models.CASCADE,
                          related_name="presupuesto")
    tarifa          = models.ForeignKey(TarifaBase, on_delete=models.PROTECT)
    costo_distancia = models.DecimalField(max_digits=10, decimal_places=2)
    costo_peajes    = models.DecimalField(max_digits=10, decimal_places=2)
    costo_ayudantes = models.DecimalField(max_digits=10, decimal_places=2)
    costo_camion    = models.DecimalField(max_digits=10, decimal_places=2)
    recargo_pisos   = models.DecimalField(max_digits=10, decimal_places=2)
    total           = models.DecimalField(max_digits=10, decimal_places=2)
    calculado_en    = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Presupuesto"

    def __str__(self):
        return f"Presupuesto mudanza #{self.mudanza_id} – ${self.total}"