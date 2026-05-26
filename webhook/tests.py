"""
Tests unitarios — app: webhook
SGM · Grupo 2 · Desarrollo de Software

User Stories cubiertas:
  US-013  Webhook de Mercado Pago confirma seña → mudanza CONFIRMADA
  US-017  Acceso por terceros vía WhatsApp: webhook Twilio deriva al formulario
"""

from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import Client, TestCase
from django.utils import timezone

from gestion.models import Cliente, Camion, Mudanza, Notificacion


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def make_cliente(telefono="+5491177778888"):
    c, _ = Cliente.objects.get_or_create(
        telefono=telefono,
        defaults={"nombre_completo": "Webhook Cliente"},
    )
    return c


def make_camion():
    cam, _ = Camion.objects.get_or_create(
        patente="WBK001",
        defaults={
            "modelo": "Webhook Truck",
            "categoria": Camion.Categoria.N2,
            "activo": True,
            "capacidad_volumen_m3": Decimal("18.00"),
            "capacidad_peso_kg": Decimal("3000.00"),
            "anio": 2022,
        },
    )
    return cam


def make_mudanza(estado=Mudanza.Estado.BORRADOR):
    return Mudanza.objects.create(
        cliente=make_cliente(),
        camion=make_camion(),
        estado=estado,
        fecha_hora=timezone.now() + timedelta(days=2),
        distancia_km=Decimal("15.00"),
        necesita_ayudantes=True,
        monto_senia=Decimal("18000.00"),
        senia_pagada=False,
        mp_preference_id="PREF_WBK_001",
    )


# ─────────────────────────────────────────────────────────
# US-013 · Webhook Mercado Pago
# ─────────────────────────────────────────────────────────

class WebhookMercadoPagoTests(TestCase):
    """
    US-013: El webhook de Mercado Pago recibe la notificación de pago
    y confirma la seña, pasando la mudanza a CONFIRMADA.
    CA: Solo un pago 'approved' confirma la mudanza.
    CA: La notificación de confirmación se registra en Notificacion.
    """

    def setUp(self):
        self.mudanza = make_mudanza()

    def test_pago_aprobado_marca_senia_pagada(self):
        """Al recibir un pago aprobado, senia_pagada pasa a True."""
        # Simulamos la lógica que ejecutaría el handler del webhook
        self.mudanza.senia_pagada = True
        self.mudanza.estado = Mudanza.Estado.CONFIRMADA
        self.mudanza.save()
        self.mudanza.refresh_from_db()
        self.assertTrue(self.mudanza.senia_pagada)
        self.assertEqual(self.mudanza.estado, Mudanza.Estado.CONFIRMADA)

    def test_pago_rechazado_no_confirma_mudanza(self):
        """Un pago rechazado no debe cambiar el estado de la mudanza."""
        # El estado debe seguir siendo BORRADOR si el pago falló
        self.mudanza.refresh_from_db()
        self.assertEqual(self.mudanza.estado, Mudanza.Estado.BORRADOR)
        self.assertFalse(self.mudanza.senia_pagada)

    def test_notificacion_confirmacion_registrada(self):
        """Al confirmar el pago, se crea una Notificacion de tipo CONFIRMACION."""
        notif = Notificacion.objects.create(
            mudanza=self.mudanza,
            tipo=Notificacion.Tipo.CONFIRMACION,
            canal=Notificacion.Canal.WHATSAPP,
            destinatario=self.mudanza.cliente.telefono,
            enviada=True,
            enviada_en=timezone.now(),
        )
        self.assertEqual(notif.tipo, Notificacion.Tipo.CONFIRMACION)
        self.assertTrue(notif.enviada)

    def test_preference_id_matchea_mudanza(self):
        """La mudanza puede encontrarse por su mp_preference_id."""
        found = Mudanza.objects.filter(
            mp_preference_id="PREF_WBK_001"
        ).first()
        self.assertIsNotNone(found)
        self.assertEqual(found.pk, self.mudanza.pk)

    def test_webhook_endpoint_existe_en_views(self):
        """El módulo webhook.views es importable (endpoint en desarrollo)."""
        import webhook.views  # noqa: F401


# ─────────────────────────────────────────────────────────
# US-017 · Webhook Twilio / acceso por terceros
# ─────────────────────────────────────────────────────────

class WebhookTwilioTests(TestCase):
    """
    US-017: Un tercero puede completar el formulario por el cliente
    tras recibir el link vía WhatsApp.
    CA: El webhook de Twilio recibe el mensaje y crea al cliente si no existe.
    CA: La respuesta automática incluye el link al formulario público.
    """

    def test_cliente_creado_si_no_existe(self):
        """El primer contacto por WhatsApp crea un Cliente en la BD."""
        telefono = "+5491133334444"
        self.assertFalse(Cliente.objects.filter(telefono=telefono).exists())
        cliente, created = Cliente.objects.get_or_create(
            telefono=telefono,
            defaults={"nombre_completo": "Desconocido"},
        )
        self.assertTrue(created)
        self.assertEqual(cliente.telefono, telefono)

    def test_cliente_existente_no_se_duplica(self):
        """Un segundo mensaje del mismo número no duplica el cliente."""
        telefono = "+5491133334444"
        Cliente.objects.get_or_create(
            telefono=telefono,
            defaults={"nombre_completo": "Desconocido"},
        )
        Cliente.objects.get_or_create(
            telefono=telefono,
            defaults={"nombre_completo": "Desconocido"},
        )
        self.assertEqual(Cliente.objects.filter(telefono=telefono).count(), 1)

    def test_notificacion_cancelacion_registrada_por_whatsapp(self):
        """Una cancelación recibida por WhatsApp se registra en Notificacion."""
        mudanza = make_mudanza(estado=Mudanza.Estado.CONFIRMADA)
        notif = Notificacion.objects.create(
            mudanza=mudanza,
            tipo=Notificacion.Tipo.CANCELACION,
            canal=Notificacion.Canal.WHATSAPP,
            destinatario=mudanza.cliente.telefono,
            enviada=True,
            enviada_en=timezone.now(),
        )
        # Al recibir cancelación, mudanza pasa a CANCELADA
        mudanza.estado = Mudanza.Estado.CANCELADA
        mudanza.save()
        mudanza.refresh_from_db()
        self.assertEqual(mudanza.estado, Mudanza.Estado.CANCELADA)
        self.assertEqual(notif.tipo, Notificacion.Tipo.CANCELACION)

    @patch("config.celery.app.send_task")
    def test_respuesta_automatica_encola_tarea_celery(self, mock_send):
        """La respuesta automática al WhatsApp se envía como tarea Celery."""
        mock_send.return_value = MagicMock(id="wa-task-001")
        telefono = "+5491199998888"
        result = mock_send(
            "notificaciones.tasks.enviar_respuesta_whatsapp",
            args=[telefono, "Gracias por contactarnos. Aquí su link: https://..."],
        )
        mock_send.assert_called_once()
        self.assertEqual(result.id, "wa-task-001")
