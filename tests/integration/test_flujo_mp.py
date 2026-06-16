"""
Tests de integración — Flujo MercadoPago
Archivo: tests/integration/test_flujo_mp.py

Cubre:
  MercadoPagoService
  ─────────────────
  [MP-01] generar_preferencia_pago → llama al SDK y devuelve sandbox_init_point
  [MP-02] generar_preferencia_pago con monto_senia=None → ValueError
  [MP-03] generar_preferencia_pago con monto_senia=0    → ValueError
  [MP-04] generar_preferencia_desde_dato (flujo landing) → devuelve URL
  [MP-05] SDK devuelve status != 200/201 → RuntimeError
  [MP-06] guardar_en=None no intenta actualizar ningún objeto
  [MP-07] mp_preference_id persiste en la Mudanza tras generar preferencia

  Webhook mp_notificacion
  ───────────────────────
  [WH-01] body inválido (JSON roto) → HTTP 200 sin procesar
  [WH-02] tipo distinto de "payment" → HTTP 200 ignorado
  [WH-03] tipo "payment" sin id → HTTP 200 ignorado
  [WH-04] pago aprobado con mudanza_uuid válido → Mudanza CONFIRMADA + senia_pagada=True
  [WH-05] pago aprobado pero estado MP != "approved" → Mudanza sin cambio
  [WH-06] pago aprobado pero mudanza_uuid no existe en DB → log, sin excepción, HTTP 200
  [WH-07] pago aprobado, Mudanza ya CONFIRMADA → idempotente, sin segundo HistorialEstado
  [WH-08] pago aprobado, Mudanza en estado inesperado (no PRESUPUESTADA) → igual confirma
  [WH-09] HistorialEstado creado correctamente al confirmar (campos y usuario sistema)
  [WH-10] error interno al procesar pago → HTTP 200 igual (MP no reintenta)

  Tareas Celery (CELERY_TASK_ALWAYS_EAGER=True)
  ─────────────────────────────────────────────
  [CEL-01] tarea enviar_notificacion_link_pago tras confirmar mudanza
           → xfail: notificaciones/tasks.py aún no implementado
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from django.test import Client, TestCase
from django.contrib.auth.models import User

from tests.integration.conftest import (
    make_cliente,
    make_mudanza,
    make_tarifa,
    make_presupuesto,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────

def _make_sdk_mock(
    status: int = 201,
    preference_id: str = "PREF-123456",
    sandbox_init_point: str = "https://sandbox.mercadopago.com/checkout/v1/redirect?pref_id=PREF-123456",
) -> MagicMock:
    """
    Devuelve un mock del mercadopago.SDK que imita la respuesta de
    sdk.preference().create() con los valores indicados.
    """
    response = {
        "status": status,
        "response": {
            "id": preference_id,
            "sandbox_init_point": sandbox_init_point,
            "init_point": sandbox_init_point.replace("sandbox.", ""),
        },
    }
    sdk = MagicMock()
    sdk.preference.return_value.create.return_value = response
    sdk.preference.return_value.get.return_value = response
    return sdk


def _make_payment_response(
    status: int = 200,
    payment_status: str = "approved",
    mudanza_uuid: str = "test-uuid",
) -> dict:
    """Imita la respuesta de sdk.payment().get(payment_id)."""
    return {
        "status": status,
        "response": {
            "status": payment_status,
            "metadata": {"mudanza_uuid": mudanza_uuid},
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# [MP-01..07] MercadoPagoService
# ─────────────────────────────────────────────────────────────────────────────

class TestMercadoPagoService(TestCase):
    """Tests unitarios de integración sobre MercadoPagoService."""

    def setUp(self) -> None:
        self.tarifa = make_tarifa()
        self.cliente = make_cliente()
        self.mudanza = make_mudanza(
            self.cliente,
            monto_senia=Decimal("15000.00"),
        )

    @patch("gestion.services.mercadopago_service._get_sdk")
    def test_mp01_generar_preferencia_pago_devuelve_url(self, mock_get_sdk: MagicMock) -> None:
        """[MP-01] Llamada exitosa devuelve sandbox_init_point."""
        mock_get_sdk.return_value = _make_sdk_mock()

        from gestion.services.mercadopago_service import MercadoPagoService

        url = MercadoPagoService.generar_preferencia_pago(self.mudanza)

        self.assertIn("sandbox.mercadopago.com", url)
        mock_get_sdk.return_value.preference.return_value.create.assert_called_once()

    def test_mp02_monto_senia_none_lanza_value_error(self) -> None:
        """[MP-02] monto_senia=None → ValueError antes de llamar al SDK."""
        from gestion.services.mercadopago_service import MercadoPagoService

        self.mudanza.monto_senia = None

        with self.assertRaises(ValueError, msg="Debe lanzar ValueError si monto_senia es None"):
            MercadoPagoService.generar_preferencia_pago(self.mudanza)

    def test_mp03_monto_senia_cero_lanza_value_error(self) -> None:
        """[MP-03] monto_senia=0 → ValueError antes de llamar al SDK."""
        from gestion.services.mercadopago_service import MercadoPagoService

        self.mudanza.monto_senia = Decimal("0.00")

        with self.assertRaises(ValueError):
            MercadoPagoService.generar_preferencia_pago(self.mudanza)

    @patch("gestion.services.mercadopago_service._get_sdk")
    def test_mp04_generar_preferencia_desde_dato_flujo_landing(self, mock_get_sdk: MagicMock) -> None:
        """[MP-04] generar_preferencia_desde_dato (landing, sin Mudanza) devuelve URL."""
        mock_get_sdk.return_value = _make_sdk_mock(preference_id="PREF-LANDING-01")

        from gestion.services.mercadopago_service import MercadoPagoService, DatoPago

        dato = DatoPago(
            uuid="some-uuid",
            titulo="Seña Mudanza Landing",
            monto=Decimal("20000.00"),
            metadata={"mudanza_id": 99, "mudanza_uuid": "some-uuid"},
        )

        url = MercadoPagoService.generar_preferencia_desde_dato(dato, guardar_en=None)

        self.assertIsInstance(url, str)
        self.assertGreater(len(url), 10)

    @patch("gestion.services.mercadopago_service._get_sdk")
    def test_mp05_sdk_error_status_lanza_runtime_error(self, mock_get_sdk: MagicMock) -> None:
        """[MP-05] SDK devuelve status 500 → RuntimeError."""
        mock_get_sdk.return_value = _make_sdk_mock(status=500)
        # Sobrescribir para que create devuelva el error
        mock_get_sdk.return_value.preference.return_value.create.return_value = {
            "status": 500,
            "response": {"message": "Internal Server Error"},
        }

        from gestion.services.mercadopago_service import MercadoPagoService

        with self.assertRaises(RuntimeError):
            MercadoPagoService.generar_preferencia_pago(self.mudanza)

    @patch("gestion.services.mercadopago_service._get_sdk")
    def test_mp06_guardar_en_none_no_falla(self, mock_get_sdk: MagicMock) -> None:
        """[MP-06] guardar_en=None no llama a .objects.filter() ni lanza errores."""
        mock_get_sdk.return_value = _make_sdk_mock()

        from gestion.services.mercadopago_service import MercadoPagoService, DatoPago

        dato = DatoPago(
            uuid="no-guardar-uuid",
            titulo="Test sin guardar",
            monto=Decimal("5000.00"),
            metadata={},
        )

        # No debe lanzar excepción
        url = MercadoPagoService.generar_preferencia_desde_dato(dato, guardar_en=None)
        self.assertIsNotNone(url)

    @patch("gestion.services.mercadopago_service._get_sdk")
    def test_mp07_preference_id_persiste_en_mudanza(self, mock_get_sdk: MagicMock) -> None:
        """[MP-07] Después de generar preferencia, mp_preference_id queda en la DB."""
        pref_id = "PREF-PERSISTENCIA-99"
        mock_get_sdk.return_value = _make_sdk_mock(preference_id=pref_id)

        from gestion.services.mercadopago_service import MercadoPagoService

        MercadoPagoService.generar_preferencia_pago(self.mudanza)

        self.mudanza.refresh_from_db()
        self.assertEqual(self.mudanza.mp_preference_id, pref_id)


# ─────────────────────────────────────────────────────────────────────────────
# [WH-01..10] Webhook mp_notificacion
# ─────────────────────────────────────────────────────────────────────────────

class TestWebhookMpNotificacion(TestCase):
    """Tests de integración del endpoint POST /webhook/mp/notificacion/."""

    ENDPOINT = "/webhook/mp/notificacion/"

    def setUp(self) -> None:
        self.client = Client()
        self.sistema_user, _ = User.objects.get_or_create(
            username="sistema",
            defaults={"is_active": False},
        )
        self.sistema_user.is_active = False
        self.sistema_user.save()

        self.tarifa = make_tarifa()
        self.cliente = make_cliente()

    def _post(self, body: dict) -> "HttpResponse":
        return self.client.post(
            self.ENDPOINT,
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_wh01_body_invalido_devuelve_200(self) -> None:
        """[WH-01] JSON roto → HTTP 200 sin procesamiento."""
        response = self.client.post(
            self.ENDPOINT,
            data="esto no es json{{",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

    def test_wh02_tipo_distinto_de_payment_devuelve_200(self) -> None:
        """[WH-02] Tipo 'merchant_order' → HTTP 200 ignorado."""
        response = self._post({"type": "merchant_order", "data": {"id": "123"}})
        self.assertEqual(response.status_code, 200)

    def test_wh03_payment_sin_id_devuelve_200(self) -> None:
        """[WH-03] Tipo 'payment' sin data.id → HTTP 200 ignorado."""
        response = self._post({"type": "payment", "data": {}})
        self.assertEqual(response.status_code, 200)

    @patch("webhook.views._get_sdk")
    def test_wh04_pago_aprobado_confirma_mudanza(self, mock_get_sdk: MagicMock) -> None:
        """[WH-04] Pago aprobado → Mudanza CONFIRMADA + senia_pagada=True."""
        from gestion.models.mudanzas import Mudanza

        mudanza = make_mudanza(
            self.cliente,
            estado=Mudanza.Estado.PRESUPUESTADA,
            monto_senia=Decimal("15000.00"),
        )

        sdk = MagicMock()
        sdk.payment.return_value.get.return_value = _make_payment_response(
            mudanza_uuid=str(mudanza.uuid)
        )
        mock_get_sdk.return_value = sdk

        response = self._post({"type": "payment", "data": {"id": "PAY-001"}})

        self.assertEqual(response.status_code, 200)
        mudanza.refresh_from_db()
        self.assertEqual(mudanza.estado, Mudanza.Estado.CONFIRMADA)
        self.assertTrue(mudanza.senia_pagada)

    @patch("webhook.views._get_sdk")
    def test_wh05_pago_no_aprobado_no_modifica_mudanza(self, mock_get_sdk: MagicMock) -> None:
        """[WH-05] estado MP 'pending' → Mudanza sin cambio."""
        from gestion.models.mudanzas import Mudanza

        mudanza = make_mudanza(
            self.cliente,
            estado=Mudanza.Estado.PRESUPUESTADA,
        )

        sdk = MagicMock()
        sdk.payment.return_value.get.return_value = _make_payment_response(
            payment_status="pending",
            mudanza_uuid=str(mudanza.uuid),
        )
        mock_get_sdk.return_value = sdk

        self._post({"type": "payment", "data": {"id": "PAY-002"}})

        mudanza.refresh_from_db()
        self.assertEqual(mudanza.estado, Mudanza.Estado.PRESUPUESTADA)
        self.assertFalse(mudanza.senia_pagada)

    @patch("webhook.views._get_sdk")
    def test_wh06_uuid_inexistente_devuelve_200_sin_excepcion(self, mock_get_sdk: MagicMock) -> None:
        """[WH-06] mudanza_uuid no existe en DB → HTTP 200, no lanza excepción."""
        sdk = MagicMock()
        sdk.payment.return_value.get.return_value = _make_payment_response(
            mudanza_uuid="uuid-que-no-existe-en-db"
        )
        mock_get_sdk.return_value = sdk

        response = self._post({"type": "payment", "data": {"id": "PAY-003"}})
        self.assertEqual(response.status_code, 200)

    @patch("webhook.views._get_sdk")
    def test_wh07_idempotente_mudanza_ya_confirmada(self, mock_get_sdk: MagicMock) -> None:
        """[WH-07] Mudanza ya CONFIRMADA → no crea segundo HistorialEstado."""
        from gestion.models.mudanzas import Mudanza
        from gestion.models.auditoria import HistorialEstado

        mudanza = make_mudanza(
            self.cliente,
            estado=Mudanza.Estado.CONFIRMADA,
            monto_senia=Decimal("15000.00"),
        )
        historial_inicial = HistorialEstado.objects.filter(mudanza=mudanza).count()

        sdk = MagicMock()
        sdk.payment.return_value.get.return_value = _make_payment_response(
            mudanza_uuid=str(mudanza.uuid)
        )
        mock_get_sdk.return_value = sdk

        self._post({"type": "payment", "data": {"id": "PAY-004"}})

        historial_final = HistorialEstado.objects.filter(mudanza=mudanza).count()
        self.assertEqual(
            historial_inicial,
            historial_final,
            "No debe crear HistorialEstado si la mudanza ya estaba CONFIRMADA",
        )

    @patch("webhook.views._get_sdk")
    def test_wh08_estado_inesperado_igual_confirma(self, mock_get_sdk: MagicMock) -> None:
        """[WH-08] Mudanza en BORRADOR (no PRESUPUESTADA) → igual transiciona a CONFIRMADA."""
        from gestion.models.mudanzas import Mudanza

        mudanza = make_mudanza(
            self.cliente,
            estado=Mudanza.Estado.BORRADOR,
            monto_senia=Decimal("15000.00"),
        )

        sdk = MagicMock()
        sdk.payment.return_value.get.return_value = _make_payment_response(
            mudanza_uuid=str(mudanza.uuid)
        )
        mock_get_sdk.return_value = sdk

        self._post({"type": "payment", "data": {"id": "PAY-005"}})

        mudanza.refresh_from_db()
        self.assertEqual(mudanza.estado, Mudanza.Estado.CONFIRMADA)

    @patch("webhook.views._get_sdk")
    def test_wh09_historial_estado_creado_correctamente(self, mock_get_sdk: MagicMock) -> None:
        """[WH-09] HistorialEstado tiene estado_anterior, estado_nuevo y usuario sistema."""
        from gestion.models.mudanzas import Mudanza
        from gestion.models.auditoria import HistorialEstado

        mudanza = make_mudanza(
            self.cliente,
            estado=Mudanza.Estado.PRESUPUESTADA,
            monto_senia=Decimal("15000.00"),
        )

        sdk = MagicMock()
        sdk.payment.return_value.get.return_value = _make_payment_response(
            mudanza_uuid=str(mudanza.uuid)
        )
        mock_get_sdk.return_value = sdk

        self._post({"type": "payment", "data": {"id": "PAY-006"}})

        historial = HistorialEstado.objects.filter(mudanza=mudanza).latest("fecha")
        self.assertEqual(historial.estado_anterior, Mudanza.Estado.PRESUPUESTADA)
        self.assertEqual(historial.estado_nuevo, Mudanza.Estado.CONFIRMADA)
        self.assertEqual(historial.usuario.username, "sistema")

    @patch("webhook.views._procesar_pago", side_effect=Exception("Error simulado de DB"))
    def test_wh10_error_interno_devuelve_200(self, mock_procesar: MagicMock) -> None:
        """[WH-10] Error interno en _procesar_pago → HTTP 200 igual (MP no reintenta)."""
        response = self._post({"type": "payment", "data": {"id": "PAY-ERR"}})
        self.assertEqual(response.status_code, 200)


# ─────────────────────────────────────────────────────────────────────────────
# [CEL-01] Celery async — xfail hasta implementar notificaciones/tasks.py
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
@pytest.mark.xfail(
    reason=(
        "notificaciones/tasks.py aún no implementado. "
        "Este test documenta el comportamiento esperado: "
        "al confirmar una mudanza vía webhook, debe dispararse la tarea "
        "Celery 'enviar_notificacion_link_pago' que crea una Notificacion "
        "LINK_PAGO en canal WHATSAPP y la marca como enviada. "
        "Cuando se implemente la tarea, quitar el mark xfail."
    ),
    strict=False,
)
def test_cel01_tarea_notificacion_link_pago_tras_confirmar(sistema_user, tarifa_activa):
    """
    [CEL-01] xfail — Al confirmar una mudanza (webhook MP), debe dispararse
    la tarea Celery 'enviar_notificacion_link_pago'.

    Con CELERY_TASK_ALWAYS_EAGER=True la tarea se ejecuta en el mismo hilo,
    por lo que podemos verificar el efecto en la DB sin broker real.

    Comportamiento esperado cuando se implemente:
      - Notificacion.objects.filter(mudanza=mudanza, tipo='LINK_PAGO').exists() → True
      - notificacion.enviada → True
      - notificacion.canal  → 'WHATSAPP'
    """
    from gestion.models.mudanzas import Mudanza
    from gestion.models import Notificacion

    # Si la tarea no existe, esto lanzará ImportError → xfail
    from notificaciones.tasks import enviar_notificacion_link_pago  # noqa: F401

    cliente = make_cliente(dni="99000001", telefono="+5491199000001")
    mudanza = make_mudanza(
        cliente,
        estado=Mudanza.Estado.PRESUPUESTADA,
        monto_senia=Decimal("15000.00"),
    )

    enviar_notificacion_link_pago.delay(mudanza_id=mudanza.pk)

    notificacion = Notificacion.objects.filter(
        mudanza=mudanza,
        tipo=Notificacion.Tipo.LINK_PAGO,
    ).first()

    assert notificacion is not None, "La tarea debe crear una Notificacion LINK_PAGO"
    assert notificacion.canal == Notificacion.Canal.WHATSAPP
    assert notificacion.enviada is True
