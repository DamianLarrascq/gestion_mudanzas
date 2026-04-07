from django.db import models
from .mudanzas import Mudanza


class Notificacion(models.Model):
    class Tipo(models.TextChoices):
        CONFIRMACION = "CONFIRMACION", "Confirmación de mudanza"
        RECORDATORIO = "RECORDATORIO", "Recordatorio 24hs"
        CANCELACION  = "CANCELACION",  "Cancelación"
        POSPOSICION  = "POSPOSICION",  "Posposición"
        LINK_PAGO    = "LINK_PAGO",    "Link de pago seña"

    class Canal(models.TextChoices):
        WHATSAPP = "WHATSAPP", "WhatsApp"
        EMAIL    = "EMAIL",    "Email"

    mudanza      = models.ForeignKey(Mudanza, on_delete=models.CASCADE,
                       related_name="notificaciones")
    tipo         = models.CharField(max_length=20, choices=Tipo.choices)
    canal        = models.CharField(max_length=20, choices=Canal.choices)
    destinatario = models.CharField(max_length=200)
    enviada      = models.BooleanField(default=False)
    enviada_en   = models.DateTimeField(null=True, blank=True)
    error        = models.TextField(blank=True)

    class Meta:
        verbose_name        = "Notificación"
        verbose_name_plural = "Notificaciones"
        ordering            = ["-enviada_en"]

    def __str__(self):
        return f"{self.get_tipo_display()} – {self.destinatario}"