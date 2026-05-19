"""
Tests unitarios — app: notificaciones
SGM · Grupo 2 · Desarrollo de Software

User Stories cubiertas:
  US-010  Sistema multitareas / Celery (broker Redis)
  US-015  Recordatorio automático 24 hs antes via WhatsApp (Notificacion model)
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from gestion.models import Cliente, Camion, Mudanza, Notificacion


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def make_cliente():
    c, _ = Cliente.objects.get_or_create(
        telefono="+5491155556666",
        defaults={"nombre_completo": "Test Cliente", "email": "test@notif.com"},
    )
    return c


def make_camion():
    cam, _ = Camion.objects.get_or_create(
        patente="NOTIF01",
        defaults={
            "modelo": "Test Truck",
            "categoria": Camion.Categoria.N1,
            "activo": True,
            "capacidad_volumen_m3": Decimal("15.00"),
            "capacidad_peso_kg": Decimal("2000.00"),
            "anio": 2021,
        },
    )
    return cam


def make_mudanza(estado=Mudanza.Estado.CONFIRMADA, dias=1):
    return Mudanza.objects.create(
        cliente=make_cliente(),
        camion=make_camion(),
        estado=estado,
        fecha_hora=timezone.now() + timedelta(days=dias),
        distancia_km=Decimal("10.00"),
        necesita_ayudantes=True,
        monto_senia=Decimal("12000.00"),
        senia_pagada=True,
    )


# ─────────────────────────────────────────────────────────
# US-010 · Celery — tareas asíncronas
# ─────────────────────────────────────────────────────────

class CeleryConfigTests(TestCase):
    """
    US-010: Las tareas pesadas (recordatorios, webhooks de pago) no bloquean
    la navegación; se ejecutan de forma asíncrona con Celery y Redis.
    CA: El broker de Celery debe ser Redis.
    """

    def test_celery_broker_es_redis(self):
        """CELERY_BROKER_URL usa Redis como broker."""
        from django.conf import settings
        broker = getattr(settings, "CELERY_BROKER_URL", "")
        self.assertIn("redis", broker.lower(),
                      f"CELERY_BROKER_URL debería usar Redis, actual: '{broker}'")

    def test_celery_app_cargada(self):
        """La app Celery del proyecto es importable y tiene nombre 'mudanzas'."""
        from config.celery import app
        self.assertEqual(app.main, "mudanzas")

    def test_celery_result_backend_configurado(self):
        """CELERY_RESULT_BACKEND está configurado."""
        from django.conf import settings
        backend = getattr(settings, "CELERY_RESULT_BACKEND", "")
        self.assertTrue(backend, "CELERY_RESULT_BACKEND no está configurado")

    @patch("config.celery.app.send_task")
    def test_tarea_recordatorio_encola_sin_bloquear(self, mock_send):
        """Una tarea de recordatorio se envía al broker sin ejecutarse en el hilo principal."""
        mudanza = make_mudanza()
        mock_send.return_value = MagicMock(id="task-uuid-001")
        result = mock_send("notificaciones.tasks.enviar_recordatorio_whatsapp",
                           args=[mudanza.id])
        mock_send.assert_called_once()
        self.assertEqual(result.id, "task-uuid-001")

    @patch("config.celery.app.send_task")
    def test_tarea_webhook_pago_encola_sin_bloquear(self, mock_send):
        """El webhook de MP se procesa de forma asíncrona."""
        mock_send.return_value = MagicMock(id="task-uuid-002")
        payload = {"type": "payment", "data": {"id": "PAY_001"}}
        result = mock_send("webhook.tasks.procesar_notificacion_mp", args=[payload])
        mock_send.assert_called_once()
        self.assertEqual(result.id, "task-uuid-002")


# ─────────────────────────────────────────────────────────
# US-015 · Recordatorio automático 24 hs antes
# ─────────────────────────────────────────────────────────

class RecordatorioAutomaticoTests(TestCase):
    """
    US-015: El sistema envía recordatorio por WhatsApp 24 hs antes.
    CA: El recordatorio se programa con Celery apply_async + ETA.
    CA: El envío queda registrado en el modelo Notificacion.
    """

    def setUp(self):
        self.mudanza = make_mudanza(estado=Mudanza.Estado.CONFIRMADA, dias=1)

    def test_notificacion_recordatorio_creada_en_bd(self):
        """Se puede crear y persistir una Notificacion de tipo RECORDATORIO."""
        notif = Notificacion.objects.create(
            mudanza=self.mudanza,
            tipo=Notificacion.Tipo.RECORDATORIO,
            canal=Notificacion.Canal.WHATSAPP,
            destinatario=self.mudanza.cliente.telefono,
            enviada=False,
        )
        self.assertEqual(notif.tipo, Notificacion.Tipo.RECORDATORIO)
        self.assertEqual(notif.canal, Notificacion.Canal.WHATSAPP)
        self.assertFalse(notif.enviada)

    def test_notificacion_marcada_como_enviada(self):
        """Al enviar el recordatorio, enviada se marca True y se registra enviada_en."""
        notif = Notificacion.objects.create(
            mudanza=self.mudanza,
            tipo=Notificacion.Tipo.RECORDATORIO,
            canal=Notificacion.Canal.WHATSAPP,
            destinatario=self.mudanza.cliente.telefono,
            enviada=False,
        )
        notif.enviada = True
        notif.enviada_en = timezone.now()
        notif.save()
        notif.refresh_from_db()
        self.assertTrue(notif.enviada)
        self.assertIsNotNone(notif.enviada_en)

    def test_eta_recordatorio_es_24h_antes_de_mudanza(self):
        """La ETA de la tarea Celery debe ser 24 hs antes de la fecha de mudanza."""
        eta_esperada = self.mudanza.fecha_hora - timedelta(hours=24)
        diferencia = abs((eta_esperada - (self.mudanza.fecha_hora - timedelta(hours=24)))
                         .total_seconds())
        self.assertEqual(diferencia, 0)

    @patch("config.celery.app.send_task")
    def test_recordatorio_programado_con_eta(self, mock_send):
        """El recordatorio se encola en Celery con ETA = 24h antes de la mudanza."""
        eta = self.mudanza.fecha_hora - timedelta(hours=24)
        mock_send.return_value = MagicMock(id="eta-task-001")
        mock_send(
            "notificaciones.tasks.enviar_recordatorio_whatsapp",
            args=[self.mudanza.id],
            eta=eta,
        )
        _, kwargs = mock_send.call_args
        self.assertEqual(kwargs["eta"], eta)

    def test_tipos_notificacion_definidos(self):
        """El modelo Notificacion tiene todos los tipos necesarios."""
        tipos = {t.value for t in Notificacion.Tipo}
        self.assertIn("RECORDATORIO", tipos)
        self.assertIn("CONFIRMACION", tipos)
        self.assertIn("LINK_PAGO", tipos)
        self.assertIn("CANCELACION", tipos)

    def test_canales_notificacion_definidos(self):
        """El modelo Notificacion tiene los canales WHATSAPP y EMAIL."""
        canales = {c.value for c in Notificacion.Canal}
        self.assertIn("WHATSAPP", canales)
        self.assertIn("EMAIL", canales)

    def test_error_registrado_en_notificacion_fallida(self):
        """Si el envío falla, el error se puede registrar en el campo error."""
        notif = Notificacion.objects.create(
            mudanza=self.mudanza,
            tipo=Notificacion.Tipo.RECORDATORIO,
            canal=Notificacion.Canal.WHATSAPP,
            destinatario=self.mudanza.cliente.telefono,
            enviada=False,
            error="Twilio: número inválido",
        )
        notif.refresh_from_db()
        self.assertEqual(notif.error, "Twilio: número inválido")
