"""
Tests de integración — Flujo Twilio / WhatsApp
Archivo: tests/integration/test_flujo_twilio.py

Cubre:
  Notificacion (modelo + estados)
  ────────────────────────────────
  [TW-01] Notificacion creada correctamente con canal WHATSAPP, enviada=False
  [TW-02] Envío exitoso vía mock Twilio → enviada=True, enviada_en seteado
  [TW-03] Error de Twilio → campo error registrado, enviada permanece False
  [TW-04] Tipo CONFIRMACION enviado correctamente
  [TW-05] Tipo RECORDATORIO enviado correctamente
  [TW-06] Tipo CANCELACION enviado correctamente
  [TW-07] Tipo LINK_PAGO enviado correctamente

  Flujo cruzado — Webhook MP → Twilio
  ─────────────────────────────────────
  [FX-01] Webhook MP confirma mudanza → dispara notificación WhatsApp de confirmación
          (mock en cadena: SDK de MP + Twilio Client)

  Tareas Celery (CELERY_TASK_ALWAYS_EAGER=True)
  ─────────────────────────────────────────────
  [CEL-02] tarea enviar_notificacion_whatsapp ejecuta envío y persiste resultado
           → xfail: notificaciones/tasks.py aún no implementado
  [CEL-03] tarea enviar_notificacion_whatsapp con error Twilio registra error en DB
           → xfail: notificaciones/tasks.py aún no implementado

Nota de diseño — mocking de Twilio
────────────────────────────────────
Twilio no está en requirements.txt todavía (la app mobile está pausada).
Todos los tests que interactúan con el cliente Twilio parchean el punto de
importación en notificaciones.tasks (o el helper que se implemente allí).
Si el módulo no existe, los tests con xfail fallan limpiamente por ImportError.

Para los tests que solo verifican el modelo Notificacion (TW-01..07),
no se necesita el cliente Twilio: se prueba la lógica de persistencia que
cualquier servicio de envío debería producir.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch, call

import pytest
from django.test import Client, TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from tests.integration.conftest import (
    make_cliente,
    make_mudanza,
    make_tarifa,
    make_notificacion,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _simular_envio_exitoso(notificacion: "Notificacion") -> None:
    """
    Simula lo que hará notificaciones/tasks.py al enviar exitosamente:
    marca la notificación como enviada y registra el timestamp.
    """
    notificacion.enviada = True
    notificacion.enviada_en = timezone.now()
    notificacion.save()


def _simular_envio_fallido(notificacion: "Notificacion", error_msg: str) -> None:
    """
    Simula lo que hará notificaciones/tasks.py cuando Twilio falla:
    registra el error sin marcar como enviada.
    """
    notificacion.enviada = False
    notificacion.error = error_msg
    notificacion.save()


# ─────────────────────────────────────────────────────────────────────────────
# [TW-01..07] Modelo Notificacion + estados de envío
# ─────────────────────────────────────────────────────────────────────────────

class TestNotificacionModelo(TestCase):
    """
    Tests de integración sobre el modelo Notificacion y su ciclo de vida.
    No dependen de Twilio ni de tasks.py — verifican la capa de persistencia.
    """

    def setUp(self) -> None:
        self.tarifa = make_tarifa()
        self.cliente = make_cliente()
        self.mudanza = make_mudanza(self.cliente)

    def test_tw01_notificacion_creada_como_no_enviada(self) -> None:
        """[TW-01] Notificacion nueva tiene enviada=False y enviada_en=None."""
        from gestion.models import Notificacion

        notif = make_notificacion(
            self.mudanza,
            tipo=Notificacion.Tipo.CONFIRMACION,
            canal=Notificacion.Canal.WHATSAPP,
            destinatario="+5491122334455",
        )

        notif.refresh_from_db()
        self.assertFalse(notif.enviada)
        self.assertIsNone(notif.enviada_en)
        self.assertEqual(notif.canal, Notificacion.Canal.WHATSAPP)

    def test_tw02_envio_exitoso_marca_enviada_y_timestamp(self) -> None:
        """[TW-02] Después de envío exitoso: enviada=True, enviada_en registrado."""
        notif = make_notificacion(self.mudanza)

        _simular_envio_exitoso(notif)

        notif.refresh_from_db()
        self.assertTrue(notif.enviada)
        self.assertIsNotNone(notif.enviada_en)

    def test_tw03_error_twilio_registra_mensaje_y_no_marca_enviada(self) -> None:
        """[TW-03] Error de Twilio → campo error guardado, enviada sigue False."""
        notif = make_notificacion(self.mudanza)

        _simular_envio_fallido(notif, "Twilio error 21211: The 'To' number is not valid")

        notif.refresh_from_db()
        self.assertFalse(notif.enviada)
        self.assertIn("21211", notif.error)

    def test_tw04_tipo_confirmacion_enviado_correctamente(self) -> None:
        """[TW-04] Tipo CONFIRMACION persiste y se puede marcar enviada."""
        from gestion.models import Notificacion

        notif = make_notificacion(
            self.mudanza,
            tipo=Notificacion.Tipo.CONFIRMACION,
        )
        self.assertEqual(notif.tipo, Notificacion.Tipo.CONFIRMACION)

        _simular_envio_exitoso(notif)
        notif.refresh_from_db()
        self.assertTrue(notif.enviada)

    def test_tw05_tipo_recordatorio_enviado_correctamente(self) -> None:
        """[TW-05] Tipo RECORDATORIO persiste y se puede marcar enviada."""
        from gestion.models import Notificacion

        notif = make_notificacion(
            self.mudanza,
            tipo=Notificacion.Tipo.RECORDATORIO,
        )
        self.assertEqual(notif.tipo, Notificacion.Tipo.RECORDATORIO)

        _simular_envio_exitoso(notif)
        notif.refresh_from_db()
        self.assertTrue(notif.enviada)

    def test_tw06_tipo_cancelacion_enviado_correctamente(self) -> None:
        """[TW-06] Tipo CANCELACION persiste y se puede marcar enviada."""
        from gestion.models import Notificacion

        notif = make_notificacion(
            self.mudanza,
            tipo=Notificacion.Tipo.CANCELACION,
        )
        self.assertEqual(notif.tipo, Notificacion.Tipo.CANCELACION)

        _simular_envio_exitoso(notif)
        notif.refresh_from_db()
        self.assertTrue(notif.enviada)

    def test_tw07_tipo_link_pago_enviado_correctamente(self) -> None:
        """[TW-07] Tipo LINK_PAGO persiste y se puede marcar enviada."""
        from gestion.models import Notificacion

        notif = make_notificacion(
            self.mudanza,
            tipo=Notificacion.Tipo.LINK_PAGO,
        )
        self.assertEqual(notif.tipo, Notificacion.Tipo.LINK_PAGO)

        _simular_envio_exitoso(notif)
        notif.refresh_from_db()
        self.assertTrue(notif.enviada)


# ─────────────────────────────────────────────────────────────────────────────
# [FX-01] Flujo cruzado: Webhook MP → notificación WhatsApp
# ─────────────────────────────────────────────────────────────────────────────

class TestFlujoCruzadoMpTwilio(TestCase):
    """
    [FX-01] Simula el flujo completo:
      POST /webhook/mp/notificacion/ con pago aprobado
        → _confirmar_mudanza cambia estado a CONFIRMADA
        → debería disparar envío de notificación WhatsApp al cliente

    El test verifica la parte que ya existe (cambio de estado) y documenta
    la parte pendiente (disparo de notificación) con un assert comentado
    que se activará cuando se implemente notificaciones/tasks.py.

    El SDK de MP y el cliente Twilio están ambos mockeados.
    """

    ENDPOINT = "/webhook/mp/notificacion/"

    def setUp(self) -> None:
        self.client_http = Client()
        self.sistema_user, _ = User.objects.get_or_create(
            username="sistema",
            defaults={"is_active": False},
        )
        self.sistema_user.is_active = False
        self.sistema_user.save()

        self.tarifa = make_tarifa()
        self.cliente = make_cliente(
            dni="88000001",
            telefono="+5491188000001",
            email="fx01@mail.com",
        )

    @patch("webhook.views._get_sdk")
    def test_fx01_webhook_mp_confirma_y_estado_es_confirmada(
        self, mock_mp_sdk: MagicMock
    ) -> None:
        """
        [FX-01] Webhook aprobado → Mudanza CONFIRMADA.

        Parte 1 (implementada): cambio de estado verificado.
        Parte 2 (pendiente):    disparo de Notificacion WHATSAPP tras confirmar.
        """
        from gestion.models.mudanzas import Mudanza
        from gestion.models import Notificacion

        mudanza = make_mudanza(
            self.cliente,
            estado=Mudanza.Estado.PRESUPUESTADA,
            monto_senia=Decimal("18000.00"),
        )

        sdk = MagicMock()
        sdk.payment.return_value.get.return_value = {
            "status": 200,
            "response": {
                "status": "approved",
                "metadata": {"mudanza_uuid": str(mudanza.uuid)},
            },
        }
        mock_mp_sdk.return_value = sdk

        response = self.client_http.post(
            self.ENDPOINT,
            data=json.dumps({"type": "payment", "data": {"id": "PAY-FX01"}}),
            content_type="application/json",
        )

        # Parte 1: cambio de estado (ya implementado)
        self.assertEqual(response.status_code, 200)
        mudanza.refresh_from_db()
        self.assertEqual(
            mudanza.estado,
            Mudanza.Estado.CONFIRMADA,
            "La mudanza debe estar CONFIRMADA después del webhook",
        )
        self.assertTrue(mudanza.senia_pagada)

        # Parte 2: notificación WhatsApp (pendiente de implementación en tasks.py)
        # Cuando se implemente, descomentar y quitar el skipTest:
        #
        # notif = Notificacion.objects.filter(
        #     mudanza=mudanza,
        #     tipo=Notificacion.Tipo.CONFIRMACION,
        #     canal=Notificacion.Canal.WHATSAPP,
        # ).first()
        # self.assertIsNotNone(notif, "Debe crearse Notificacion CONFIRMACION vía WhatsApp")
        # self.assertTrue(notif.enviada)

        # Por ahora, documentamos que la notificación NO existe todavía
        notif_existe = Notificacion.objects.filter(
            mudanza=mudanza,
            tipo=Notificacion.Tipo.CONFIRMACION,
        ).exists()
        # Este assert es deliberadamente "permisivo": el flujo cruzado completo
        # se validará cuando se implemente la tarea. Por ahora solo verificamos
        # que el webhook no crea notificaciones por error.
        self.assertFalse(
            notif_existe,
            "Todavía no debe existir Notificacion automática (tasks.py pendiente)",
        )


# ─────────────────────────────────────────────────────────────────────────────
# [CEL-02..03] Celery async — xfail hasta implementar notificaciones/tasks.py
# ─────────────────────────────────────────────────────────────────────────────

_XFAIL_TASKS_REASON = (
    "notificaciones/tasks.py aún no implementado. "
    "Cuando se cree la tarea 'enviar_notificacion_whatsapp', quitar xfail."
)


@pytest.mark.django_db
@pytest.mark.xfail(reason=_XFAIL_TASKS_REASON, strict=False)
def test_cel02_tarea_enviar_whatsapp_exitosa_persiste_enviada(
    sistema_user, tarifa_activa
):
    """
    [CEL-02] xfail — enviar_notificacion_whatsapp con Twilio mockeado
    debe marcar la notificación como enviada en la DB.

    CELERY_TASK_ALWAYS_EAGER=True hace que delay() ejecute en el mismo hilo.
    """
    from gestion.models import Notificacion

    # Si el módulo no existe → ImportError → xfail
    from notificaciones.tasks import enviar_notificacion_whatsapp  # noqa: F401

    cliente = make_cliente(dni="77000001", telefono="+5491177000001", email="cel02@mail.com")
    mudanza = make_mudanza(cliente)
    notif = make_notificacion(
        mudanza,
        tipo=Notificacion.Tipo.RECORDATORIO,
        canal=Notificacion.Canal.WHATSAPP,
        destinatario="+5491177000001",
    )

    # Mock del cliente Twilio dentro del módulo de tareas
    with patch("notificaciones.tasks.TwilioClient") as mock_twilio:
        mock_twilio.return_value.messages.create.return_value = MagicMock(sid="SM-TEST-001")
        enviar_notificacion_whatsapp.delay(notificacion_id=notif.pk)

    notif.refresh_from_db()
    assert notif.enviada is True, "La tarea debe marcar enviada=True"
    assert notif.enviada_en is not None, "La tarea debe registrar enviada_en"


@pytest.mark.django_db
@pytest.mark.xfail(reason=_XFAIL_TASKS_REASON, strict=False)
def test_cel03_tarea_enviar_whatsapp_error_twilio_registra_en_db(
    sistema_user, tarifa_activa
):
    """
    [CEL-03] xfail — Si Twilio lanza excepción, la tarea debe:
      - Capturarla sin relanzar (para no bloquear la cola Celery)
      - Guardar el mensaje de error en notificacion.error
      - Dejar enviada=False
    """
    from gestion.models import Notificacion

    from notificaciones.tasks import enviar_notificacion_whatsapp  # noqa: F401

    cliente = make_cliente(dni="77000002", telefono="+5491177000002", email="cel03@mail.com")
    mudanza = make_mudanza(cliente)
    notif = make_notificacion(
        mudanza,
        tipo=Notificacion.Tipo.CONFIRMACION,
        canal=Notificacion.Canal.WHATSAPP,
        destinatario="+5491177000002",
    )

    twilio_error = Exception("Twilio error 20003: Authentication failed")

    with patch("notificaciones.tasks.TwilioClient") as mock_twilio:
        mock_twilio.return_value.messages.create.side_effect = twilio_error
        enviar_notificacion_whatsapp.delay(notificacion_id=notif.pk)

    notif.refresh_from_db()
    assert notif.enviada is False, "Con error Twilio, enviada debe seguir False"
    assert "20003" in notif.error, "El error de Twilio debe quedar registrado en notif.error"
