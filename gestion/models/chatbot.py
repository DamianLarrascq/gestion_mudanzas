from django.db import models
from django.utils import timezone


class SesionChatbot(models.Model):
    """
    Registro de una conversacion activa con el bot.

    Una sesion se identifica por 'canal_id' (telefono en WA, session_key en web).
    El campo 'atencion_manual' bloquea respuestas automaticas cuando el operador toma el hilo.
    """

    class Canal(models.TextChoices):
        WHATSAPP = 'WHATSAPP', 'WhatsApp'
        WEB = 'WEB', 'Pop-up Web'


    class Flujo(models.TextChoices):
        LANDING = 'LANDING', 'Entrada desde Landing Page'
        GENERAL = 'GENERAL', 'Entrada General'
        DESCONOCIDO = 'DESCONOCIDO', 'Desconocido'

    canal_id = models.CharField(
        max_length=100,
        db_index=True,
        help_text='Telefono (WA) o sesion_key (web).',
    )
    canal = models.CharField(max_length=20, choices=Canal.choices)
    flujo_detectado = models.CharField(
        max_length=20,
        choices=Flujo.choices,
        default=Flujo.DESCONOCIDO,
    )
    atencion_manual = models.BooleanField(
        default=False,
        help_text='True cuando el usuario solicito hablar con un operador.'
    )
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Sesion de chatbot'
        verbose_name_plural = 'Sesiones de chatbot'
        unique_together = [['canal_id', 'canal']]
        ordering = ['-actualizada_en']

    def __str__(self):
        return f'[{self.canal}] {self.canal_id} - {self.flujo_detectado}'


class MensajeChatbot(models.Model):
    """
    Log inmutable de cada intercambio. Util de para auditoria y para que el operador vea el historial cuando toma la conversacion.
    """

    class Origen(models.TextChoices):
        USUARIO = 'USUARIO', 'Usuario'
        BOT = 'BOT', 'Bot'

    sesion = models.ForeignKey(
        SesionChatbot,
        on_delete=models.CASCADE,
        related_name='mensajes',
    )
    origen = models.CharField(max_length=10, choices=Origen.choices)
    texto = models.TextField()
    enviado_en = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Mensaje de chatbot'
        verbose_name_plural = 'Mensajes de chatbot'
        ordering = ['enviado_en']

    def __str__(self):
        return f'[{self.origen}] {self.texto[:60]}'
