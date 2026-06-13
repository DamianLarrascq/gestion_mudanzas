"""
Tests de integración — Capas + Flujos de negocio + Flujos cruzados
Archivo: tests/integration/test_capas.py

Cubre:
  PresupuestoService
  ──────────────────
  [PS-01] calcular_y_persistir → persiste Presupuesto en DB y actualiza distancia_km
  [PS-02] calcular_y_persistir con distancia_km <= 0 → ValidationError
  [PS-03] calcular_y_persistir sin tarifa activa → ValidationError
  [PS-04] calcular_y_persistir update_or_create: segunda llamada actualiza, no duplica
  [PS-05] validar_capacidad_camion sin camión asignado → puede_transportar=True
  [PS-06] validar_capacidad_camion con sobrecarga de peso → sobrecarga_peso=True
  [PS-07] validar_capacidad_camion dentro de límites → puede_transportar=True

  SolicitudLanding (procesar_solicitud_landing)
  ─────────────────────────────────────────────
  [SL-01] flujo completo: crea Cliente + Mudanza + ItemInventario + Presupuesto en una tx
  [SL-02] inventario vacío → ValidationError
  [SL-03] catalogo_item_id inexistente → ValidationError
  [SL-04] cliente ya existente (mismo teléfono) → get_or_create no duplica

  Views — capas HTTP→Service→DB
  ──────────────────────────────
  [VI-01] ResumenMudanzaView GET con presupuesto existente → 200, contexto correcto
  [VI-02] ResumenMudanzaView GET sin presupuesto → 200, tiene_presupuesto=False
  [VI-03] ResumenMudanzaView POST recalcula y persiste nuevo presupuesto
  [VI-04] ResumenMudanzaView POST sin distancia → error en contexto, no redirige
  [VI-05] ClienteDetailView requiere login → 302 sin sesión
  [VI-06] ClienteDetailView con login → 200
  [VI-07] MudanzaListView → 200, lista vacía o con datos
  [VI-08] api_validar_capacidad_camion → JSON con estructura correcta

  Flujo cruzado completo
  ──────────────────────
  [FC-01] MudanzaCreateService.crear → PresupuestoService.calcular → webhook confirma
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client, TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from tests.integration.conftest import (
    make_camion,
    make_catalogo_item,
    make_cliente,
    make_direccion,
    make_mudanza,
    make_presupuesto,
    make_tarifa,
    make_user,
    make_empleado,
)


# ─────────────────────────────────────────────────────────────────────────────
# [PS-01..07] PresupuestoService
# ─────────────────────────────────────────────────────────────────────────────

class TestPresupuestoService(TestCase):
    """Integración de capas: PresupuestoService ↔ DB."""

    def setUp(self) -> None:
        self.tarifa = make_tarifa()
        self.cliente = make_cliente()
        self.mudanza = make_mudanza(self.cliente)
        # Catalogo item para que el inventario no esté vacío
        self.item = make_catalogo_item()

    def test_ps01_calcular_y_persistir_crea_presupuesto_en_db(self) -> None:
        """[PS-01] calcular_y_persistir persiste Presupuesto y actualiza distancia_km."""
        from gestion.models import Presupuesto
        from gestion.services.presupuesto_service import PresupuestoService

        ctx = PresupuestoService.calcular_y_persistir(
            mudanza_id=self.mudanza.pk,
            distancia_km="20.00",
        )

        self.assertIn("monto_total_raw", ctx)
        self.assertGreater(ctx["monto_total_raw"], 0)

        presupuesto = Presupuesto.objects.get(mudanza=self.mudanza)
        self.assertEqual(presupuesto.tarifa, self.tarifa)
        self.assertGreater(presupuesto.total, 0)

        self.mudanza.refresh_from_db()
        self.assertEqual(self.mudanza.distancia_km, Decimal("20.00"))

    def test_ps02_distancia_cero_lanza_validation_error(self) -> None:
        """[PS-02] distancia_km <= 0 → ValidationError."""
        from django.core.exceptions import ValidationError
        from gestion.services.presupuesto_service import PresupuestoService

        with self.assertRaises(ValidationError):
            PresupuestoService.calcular_y_persistir(
                mudanza_id=self.mudanza.pk,
                distancia_km="0",
            )

    def test_ps03_sin_tarifa_activa_lanza_validation_error(self) -> None:
        """[PS-03] Sin TarifaBase activa → ValidationError."""
        from django.core.exceptions import ValidationError
        from gestion.models import TarifaBase
        from gestion.services.presupuesto_service import PresupuestoService

        TarifaBase.objects.update(activa=False)

        with self.assertRaises(ValidationError):
            PresupuestoService.calcular_y_persistir(
                mudanza_id=self.mudanza.pk,
                distancia_km="15.00",
            )

    def test_ps04_segunda_llamada_actualiza_sin_duplicar(self) -> None:
        """[PS-04] update_or_create: segunda llamada actualiza el Presupuesto existente."""
        from gestion.models import Presupuesto
        from gestion.services.presupuesto_service import PresupuestoService

        PresupuestoService.calcular_y_persistir(
            mudanza_id=self.mudanza.pk,
            distancia_km="10.00",
        )
        PresupuestoService.calcular_y_persistir(
            mudanza_id=self.mudanza.pk,
            distancia_km="25.00",
        )

        count = Presupuesto.objects.filter(mudanza=self.mudanza).count()
        self.assertEqual(count, 1, "Debe existir exactamente 1 Presupuesto por mudanza")

        presupuesto = Presupuesto.objects.get(mudanza=self.mudanza)
        self.mudanza.refresh_from_db()
        self.assertEqual(self.mudanza.distancia_km, Decimal("25.00"))

    def test_ps05_validar_capacidad_sin_camion(self) -> None:
        """[PS-05] Sin camión asignado → puede_transportar=True, camion_asignado=False."""
        from gestion.services.presupuesto_service import PresupuestoService

        mudanza_sin_camion = make_mudanza(self.cliente, camion=None)

        resultado = PresupuestoService.validar_capacidad_camion(mudanza_sin_camion.pk)

        self.assertFalse(resultado["camion_asignado"])
        self.assertTrue(resultado["puede_transportar"])
        self.assertIsNone(resultado["capacidad_volumen_m3"])

    def test_ps06_validar_capacidad_sobrecarga_peso(self) -> None:
        """[PS-06] Inventario supera peso del camión → sobrecarga_peso=True."""
        from gestion.models import ItemInventario, Camion
        from gestion.services.presupuesto_service import PresupuestoService

        camion = make_camion(
            patente="SOBP001",
            capacidad_volumen_m3=Decimal("50.00"),
            capacidad_peso_kg=Decimal("100.00"),   # límite muy bajo
        )
        mudanza = make_mudanza(self.cliente, camion=camion)

        # Item muy pesado: 3 × 80 kg = 240 kg > 100 kg
        ItemInventario.objects.create(
            mudanza=mudanza,
            catalogo_item=self.item,
            cantidad=3,
        )

        resultado = PresupuestoService.validar_capacidad_camion(mudanza.pk)

        self.assertTrue(resultado["sobrecarga_peso"])
        self.assertFalse(resultado["puede_transportar"])

    def test_ps07_validar_capacidad_dentro_de_limites(self) -> None:
        """[PS-07] Inventario dentro de límites → puede_transportar=True."""
        from gestion.models import ItemInventario
        from gestion.services.presupuesto_service import PresupuestoService

        camion = make_camion(
            patente="OKCA001",
            capacidad_volumen_m3=Decimal("50.00"),
            capacidad_peso_kg=Decimal("5000.00"),
        )
        mudanza = make_mudanza(self.cliente, camion=camion)

        ItemInventario.objects.create(
            mudanza=mudanza,
            catalogo_item=self.item,
            cantidad=1,
        )

        resultado = PresupuestoService.validar_capacidad_camion(mudanza.pk)

        self.assertTrue(resultado["puede_transportar"])
        self.assertFalse(resultado["sobrecarga_peso"])
        self.assertFalse(resultado["sobrecarga_volumen"])


# ─────────────────────────────────────────────────────────────────────────────
# [SL-01..04] SolicitudLanding
# ─────────────────────────────────────────────────────────────────────────────

class TestSolicitudLanding(TestCase):
    """
    Integración: procesar_solicitud_landing crea toda la estructura en una tx.
    MP siempre mockeado.
    """

    def setUp(self) -> None:
        self.tarifa = make_tarifa()
        self.item = make_catalogo_item(nombre="Mesa comedor")

    def _form_data(self, **overrides) -> dict:
        """Datos mínimos válidos para SolicitudPresupuestoForm."""
        from django.utils import timezone as dtz

        data = {
            "nombre": "Solange Cruz",
            "telefono": "+5491155000001",
            "email": "sc@test.com",
            "origen_calle": "Av. Rivadavia",
            "origen_numero": "3000",
            "origen_localidad": "CABA",
            "origen_piso": "PB",
            "origen_ascensor": False,
            "destino_calle": "Av. Santa Fe",
            "destino_numero": "1000",
            "destino_localidad": "CABA",
            "fecha_deseada": dtz.now() + __import__("datetime").timedelta(days=5),
            "distancia_km": "15",
        }
        data.update(overrides)
        return data

    @patch("public.services.solicitud_service.MercadoPagoService.generar_preferencia_desde_dato")
    def test_sl01_flujo_completo_crea_estructura_en_db(self, mock_mp: MagicMock) -> None:
        """[SL-01] Flujo landing crea Cliente + Mudanza + ItemInventario + Presupuesto."""
        from gestion.models import Mudanza, Presupuesto
        from gestion.models.clientes import Cliente
        from public.services.solicitud_service import procesar_solicitud_landing

        mock_mp.return_value = "https://sandbox.mercadopago.com/checkout/test"

        resultado = procesar_solicitud_landing(
            form_data=self._form_data(),
            inventario_raw=[{"catalogo_item_id": self.item.pk, "cantidad": 2}],
        )

        self.assertIn("pago_url", resultado)
        self.assertIn("mudanza_id", resultado)
        self.assertIn("monto_total", resultado)
        self.assertIn("monto_senia", resultado)

        mudanza = Mudanza.objects.get(pk=resultado["mudanza_id"])
        self.assertEqual(mudanza.estado, Mudanza.Estado.PRESUPUESTADA)
        self.assertTrue(mudanza.inventario.exists())
        self.assertTrue(Presupuesto.objects.filter(mudanza=mudanza).exists())
        self.assertTrue(Cliente.objects.filter(telefono="+5491155000001").exists())

    @patch("public.services.solicitud_service.MercadoPagoService.generar_preferencia_desde_dato")
    def test_sl02_inventario_vacio_lanza_validation_error(self, mock_mp: MagicMock) -> None:
        """[SL-02] inventario_raw vacío → ValidationError antes de crear nada."""
        from django.core.exceptions import ValidationError
        from public.services.solicitud_service import procesar_solicitud_landing

        with self.assertRaises(ValidationError, msg="Inventario vacío debe lanzar ValidationError"):
            procesar_solicitud_landing(
                form_data=self._form_data(),
                inventario_raw=[],
            )

    @patch("public.services.solicitud_service.MercadoPagoService.generar_preferencia_desde_dato")
    def test_sl03_catalogo_item_inexistente_lanza_validation_error(self, mock_mp: MagicMock) -> None:
        """[SL-03] catalogo_item_id 99999 no existe → ValidationError."""
        from django.core.exceptions import ValidationError
        from public.services.solicitud_service import procesar_solicitud_landing

        with self.assertRaises(ValidationError):
            procesar_solicitud_landing(
                form_data=self._form_data(),
                inventario_raw=[{"catalogo_item_id": 99999, "cantidad": 1}],
            )

    @patch("public.services.solicitud_service.MercadoPagoService.generar_preferencia_desde_dato")
    def test_sl04_cliente_existente_no_se_duplica(self, mock_mp: MagicMock) -> None:
        """[SL-04] Mismo teléfono → get_or_create reutiliza el Cliente existente."""
        from gestion.models.clientes import Cliente
        from public.services.solicitud_service import procesar_solicitud_landing

        mock_mp.return_value = "https://sandbox.mercadopago.com/checkout/test"

        item2 = make_catalogo_item(nombre="Heladera SL04")
        form = self._form_data(telefono="+5491155000002", email="dup@test.com")

        procesar_solicitud_landing(
            form_data=form,
            inventario_raw=[{"catalogo_item_id": item2.pk, "cantidad": 1}],
        )
        procesar_solicitud_landing(
            form_data=form,
            inventario_raw=[{"catalogo_item_id": item2.pk, "cantidad": 1}],
        )

        count = Cliente.objects.filter(telefono="+5491155000002").count()
        self.assertEqual(count, 1, "No debe haber clientes duplicados con el mismo teléfono")


# ─────────────────────────────────────────────────────────────────────────────
# [VI-01..08] Views
# ─────────────────────────────────────────────────────────────────────────────

class TestViews(TestCase):
    """Integración HTTP → Service → DB."""

    def setUp(self) -> None:
        self.tarifa = make_tarifa()
        self.cliente = make_cliente()
        self.mudanza = make_mudanza(self.cliente)

        # Usuario staff autenticado
        self.user = User.objects.create_user(
            username="view_staff", password="Pass1234!", is_staff=True
        )
        self.client.login(username="view_staff", password="Pass1234!")

    def test_vi01_resumen_get_con_presupuesto_devuelve_200(self) -> None:
        """[VI-01] ResumenMudanzaView GET con presupuesto existente → 200."""
        presupuesto = make_presupuesto(self.mudanza, self.tarifa)

        response = self.client.get(f"/gestion/mudanzas/{self.mudanza.pk}/resumen/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["tiene_presupuesto"])
        self.assertIn("monto_total_formateado", response.context)

    def test_vi02_resumen_get_sin_presupuesto_tiene_presupuesto_false(self) -> None:
        """[VI-02] ResumenMudanzaView GET sin presupuesto → tiene_presupuesto=False."""
        response = self.client.get(f"/gestion/mudanzas/{self.mudanza.pk}/resumen/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["tiene_presupuesto"])

    @patch("gestion.views.MercadoPagoService.generar_preferencia_pago")
    def test_vi03_resumen_post_recalcula_y_persiste(self, mock_mp: MagicMock) -> None:
        """[VI-03] ResumenMudanzaView POST persiste presupuesto con nueva distancia."""
        from gestion.models import Presupuesto

        mock_mp.return_value = "https://sandbox.mercadopago.com/checkout/test"

        response = self.client.post(
            f"/gestion/mudanzas/{self.mudanza.pk}/resumen/",
            data={
                "distancia_km": "30",
                "costo_peajes": "500",
                "generar_pago": "0",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Presupuesto.objects.filter(mudanza=self.mudanza).exists())
        self.mudanza.refresh_from_db()
        self.assertEqual(self.mudanza.distancia_km, Decimal("30.00"))

    def test_vi04_resumen_post_sin_distancia_devuelve_error_en_contexto(self) -> None:
        """[VI-04] ResumenMudanzaView POST sin distancia → error en contexto, sin redirect."""
        response = self.client.post(
            f"/gestion/mudanzas/{self.mudanza.pk}/resumen/",
            data={"distancia_km": "", "costo_peajes": "0"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context.get("error"))

    def test_vi05_cliente_detail_sin_login_redirige(self) -> None:
        """[VI-05] ClienteDetailView sin sesión → 302 a login."""
        self.client.logout()
        response = self.client.get(f"/gestion/clientes/{self.cliente.pk}/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_vi06_cliente_detail_con_login_devuelve_200(self) -> None:
        """[VI-06] ClienteDetailView con login → 200."""
        response = self.client.get(f"/gestion/clientes/{self.cliente.pk}/")
        self.assertEqual(response.status_code, 200)

    def test_vi07_mudanza_list_devuelve_200(self) -> None:
        """[VI-07] MudanzaListView → 200."""
        response = self.client.get("/gestion/mudanzas/")
        self.assertEqual(response.status_code, 200)

    def test_vi08_api_validar_capacidad_devuelve_json_correcto(self) -> None:
        """[VI-08] api_validar_capacidad_camion → JSON con claves esperadas."""
        response = self.client.get(
            f"/gestion/mudanzas/{self.mudanza.pk}/validar-capacidad/"
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)

        claves_esperadas = {
            "camion_asignado",
            "volumen_total_m3",
            "peso_total_kg",
            "puede_transportar",
        }
        for clave in claves_esperadas:
            self.assertIn(clave, data, f"Falta clave '{clave}' en la respuesta JSON")


# ─────────────────────────────────────────────────────────────────────────────
# [FC-01] Flujo cruzado completo
# ─────────────────────────────────────────────────────────────────────────────

class TestFlujoCruzadoCompleto(TestCase):
    """
    [FC-01] MudanzaCreateService.crear → PresupuestoService.calcular → webhook confirma.

    Verifica que las tres capas interactúan correctamente en secuencia,
    sin efectos secundarios ni datos corruptos en DB.
    """

    def setUp(self) -> None:
        self.tarifa = make_tarifa()
        self.cliente = make_cliente(dni="FC01DNI1", telefono="+5491100FC001", email="fc01@test.com")
        self.camion = make_camion(patente="FC01CAM")
        self.sistema_user, _ = User.objects.get_or_create(
            username="sistema",
            defaults={"is_active": False},
        )
        self.sistema_user.is_active = False
        self.sistema_user.save()

    @patch("webhook.views._get_sdk")
    def test_fc01_crear_presupuestar_confirmar_via_webhook(self, mock_sdk: MagicMock) -> None:
        """
        [FC-01] Flujo completo de 3 etapas:
          1. Crear mudanza vía MudanzaCreateService
          2. Calcular presupuesto vía PresupuestoService
          3. Confirmar vía webhook MP mockeado
        """
        from gestion.models.mudanzas import Mudanza
        from gestion.models import Presupuesto
        from gestion.models.auditoria import HistorialEstado
        from gestion.services.mudanza_create_service import (
            MudanzaCreateService,
            MudanzaCreateInput,
            DireccionInput,
        )
        from gestion.services.presupuesto_service import PresupuestoService

        # ── Etapa 1: crear mudanza ────────────────────────────────────────────
        staff_user = User.objects.create_user(
            username="fc01_staff", password="Pass1234!", is_staff=True
        )

        origen = DireccionInput(
            calle="Av. Corrientes",
            numero="1234",
            localicad="CABA",
            provincia="Buenos Aires",
            codigo_postal="1043",
            piso="PB",
            departamento="",
            tiene_ascensor=False,
            ascensor_grande=False,
            capacidad_ascensor_kg=None,
        )
        destino = DireccionInput(
            calle="Av. Santa Fe",
            numero="567",
            localicad="CABA",
            provincia="Buenos Aires",
            codigo_postal="1059",
            piso="2",
            departamento="B",
            tiene_ascensor=True,
            ascensor_grande=False,
            capacidad_ascensor_kg=None,
        )
        data = MudanzaCreateInput(
            cliente_id=self.cliente.pk,
            fecha_hora=timezone.now() + __import__("datetime").timedelta(days=3),
            necesita_ayudantes=True,
            camion_id=self.camion.pk,
            monto_senia=Decimal("20000.00"),
            origen=origen,
            destino=destino,
            asignaciones=[],
            inventario=[],
        )

        resultado_creacion = MudanzaCreateService.crear(data, usuario=staff_user)
        mudanza_id = resultado_creacion["id"]
        mudanza = Mudanza.objects.get(pk=mudanza_id)

        self.assertIn(mudanza.estado, [Mudanza.Estado.BORRADOR, Mudanza.Estado.PRESUPUESTADA])

        # ── Etapa 2: calcular presupuesto ─────────────────────────────────────
        ctx = PresupuestoService.calcular_y_persistir(
            mudanza_id=mudanza_id,
            distancia_km="18.00",
        )

        self.assertGreater(ctx["monto_total_raw"], 0)
        self.assertTrue(Presupuesto.objects.filter(mudanza=mudanza).exists())

        # Transicionar a PRESUPUESTADA para que el webhook pueda confirmar
        Mudanza.objects.filter(pk=mudanza_id).update(estado=Mudanza.Estado.PRESUPUESTADA)
        mudanza.refresh_from_db()

        # ── Etapa 3: confirmar vía webhook ────────────────────────────────────
        sdk = MagicMock()
        sdk.payment.return_value.get.return_value = {
            "status": 200,
            "response": {
                "status": "approved",
                "metadata": {"mudanza_uuid": str(mudanza.uuid)},
            },
        }
        mock_sdk.return_value = sdk

        client_http = Client()
        response = client_http.post(
            "/webhook/mp/notificacion/",
            data=json.dumps({"type": "payment", "data": {"id": "PAY-FC01"}}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        mudanza.refresh_from_db()
        self.assertEqual(
            mudanza.estado,
            Mudanza.Estado.CONFIRMADA,
            "Después del flujo completo la mudanza debe estar CONFIRMADA",
        )
        self.assertTrue(mudanza.senia_pagada)

        # Verificar que el HistorialEstado registra la transición correcta
        historial = HistorialEstado.objects.filter(
            mudanza=mudanza,
            estado_nuevo=Mudanza.Estado.CONFIRMADA,
        )
        self.assertTrue(
            historial.exists(),
            "Debe existir HistorialEstado con estado_nuevo=CONFIRMADA",
        )
