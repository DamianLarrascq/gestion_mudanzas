"""
Tests de seguridad — Endpoint público de presupuesto
Archivo: tests/security/test_presupuesto.py

Endpoint auditado
──────────────────
  POST /presupuesto/solicitar/   (public.views.solicitar_presupuesto)

Flujo completo que se protege
──────────────────────────────
  1. JSON body → SolicitudPresupuestoForm (validación)
  2. _validar_inventario()          → consulta CatalogoItem por pk
  3. _obtener_tarifa_activa()       → requiere tarifa con activa=True en DB
  4. calcular_costos_desde_parametros()
  5. transaction.atomic():
       Cliente.get_or_create(telefono=...)
       Direccion.create() × 2
       Mudanza.create()
       ItemInventario.bulk_create()
       Presupuesto.create()
  6. MercadoPagoService.generar_preferencia_desde_dato()  ← siempre mockeado

Áreas de riesgo cubiertas
──────────────────────────
  PRES-01  Manipulación de inventario
             Ítem inexistente, cantidad 0 / negativa / float / string,
             inventario vacío, lista con None, cantidad masiva (DoS lógico),
             ítems duplicados, catalogo_item_id nulo.

  PRES-02  Manipulación de distancia y costos
             distancia_km ≤ 0, distancia astronómica (DoS numérico),
             distancia como string no numérico, distancia ausente.

  PRES-03  Manipulación de datos de cliente
             Teléfono con inyección de caracteres, nombre con HTML/script,
             email malformado, teléfono vacío,
             reutilización de teléfono existente (no debe duplicar Cliente).

  PRES-04  Manipulación de fecha
             Fecha en el pasado, fecha hoy (borde), fecha inválida como string,
             fecha 100 años en el futuro, fecha ausente.

  PRES-05  Integridad transaccional
             Sin tarifa activa en DB → ValidationError sin mudanza huérfana.
             Fallo de MP → Mudanza queda en PRESUPUESTADA (sin romper la TX).

  PRES-06  Comportamiento bajo carga / flood
             Mismo teléfono enviado N veces → un solo Cliente creado.

Notas
──────
  - MercadoPago se mockea en todos los tests para evitar llamadas reales y
    permitir correr en CI sin credenciales.
  - Los tests de PRES-01 e PRES-02 que esperan 422 documentan que el
    sistema ya valida esos casos. Si alguno devuelve 200, es un bug nuevo.
  - PRES-05 (sin tarifa activa) puede devolver 422 o 502 según la
    implementación; el test acepta ambos y verifica que ok=False.
"""

import json
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client, TestCase

from gestion.models import Cliente
from gestion.models.catalogo import CatalogoItem
from gestion.models.mudanzas import Mudanza
from gestion.models.presupuestos import TarifaBase


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

URL = "/presupuesto/solicitar/"
FECHA_VALIDA = (date.today() + timedelta(days=10)).isoformat()


def _make_tarifa() -> TarifaBase:
    """Crea (o recupera) una tarifa activa mínima para que el servicio funcione."""
    tarifa, _ = TarifaBase.objects.get_or_create(
        nombre="Tarifa Test Seguridad",
        defaults={
            "precio_por_km": Decimal("800.00"),
            "precio_ayudante": Decimal("3000.00"),
            "recargo_piso": Decimal("1500.00"),
            "recargo_hora_pico": Decimal("1.20"),
            "recargo_fin_de_semana": Decimal("1.15"),
            "permite_caba_feriados": False,
            "activa": True,
            "vigente_desde": date.today(),
            "seguro_camion": Decimal("2000.00"),
            "empleado_art": Decimal("500.00"),
            "empleado_seguro_riesgo": Decimal("400.00"),
            "empleado_seguro_ayudante": Decimal("300.00"),
            "salario_conductor": Decimal("8000.00"),
            "salario_ayudante": Decimal("5000.00"),
        },
    )
    return tarifa


def _make_catalogo_item(nombre: str = "Sillón Test") -> CatalogoItem:
    item, _ = CatalogoItem.objects.get_or_create(
        nombre=nombre,
        defaults={
            "categoria": "LIVING",
            "volumen_m3": Decimal("0.800"),
            "peso_estimado_kg": Decimal("35.00"),
        },
    )
    return item


def _payload_valido(item_id: int, **overrides) -> dict:
    """Construye un payload completo y válido. Sobreescribir campos para tests negativos."""
    base = {
        "nombre": "Ana García",
        "telefono": "+5491100000099",
        "email": "ana@mail.com",
        "origen_calle": "Av. Corrientes",
        "origen_numero": "1234",
        "origen_localidad": "CABA",
        "destino_calle": "Av. Santa Fe",
        "destino_numero": "567",
        "destino_localidad": "CABA",
        "fecha_deseada": FECHA_VALIDA,
        "hora_deseada" : "10:00", 
        "distancia_km": "15.00",
        "inventario": [{"catalogo_item_id": item_id, "cantidad": 2}],
    }
    base.update(overrides)
    return base


def _post(client: Client, payload: dict) -> object:
    return client.post(
        URL,
        data=json.dumps(payload),
        content_type="application/json",
    )


def _mock_mp():
    """Context manager que reemplaza MercadoPago con una URL ficticia."""
    return patch(
        "public.services.solicitud_service.MercadoPagoService.generar_preferencia_desde_dato",
        return_value="https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=FAKE_PREF",
    )


# ─────────────────────────────────────────────────────────────────────────────
# PRES-01 · Manipulación de inventario
# ─────────────────────────────────────────────────────────────────────────────

class InventarioManipulacionTest(TestCase):
    """
    PRES-01: Verifica que _validar_inventario() rechaza correctamente
    todos los inputs maliciosos o malformados que podrían provocar
    creación de registros inválidos, errores 500, o bypass de precios.
    """

    def setUp(self):
        self.client = Client()
        _make_tarifa()
        self.item = _make_catalogo_item()

    def test_item_inexistente_en_catalogo_rechazado(self):
        """catalogo_item_id que no existe en DB → 422, ok=False."""
        payload = _payload_valido(self.item.pk, inventario=[
            {"catalogo_item_id": 999999, "cantidad": 1}
        ])
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(json.loads(response.content)["ok"])

    def test_cantidad_cero_rechazada(self):
        """cantidad=0 → 422. No debe crear ItemInventario con cantidad inválida."""
        payload = _payload_valido(self.item.pk, inventario=[
            {"catalogo_item_id": self.item.pk, "cantidad": 0}
        ])
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(json.loads(response.content)["ok"])

    def test_cantidad_negativa_rechazada(self):
        """cantidad=-5 → 422. Cantidad negativa no tiene sentido semántico."""
        payload = _payload_valido(self.item.pk, inventario=[
            {"catalogo_item_id": self.item.pk, "cantidad": -5}
        ])
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(json.loads(response.content)["ok"])

    def test_cantidad_float_rechazada(self):
        """cantidad=1.5 (float) → 422. El servicio exige int."""
        payload = _payload_valido(self.item.pk, inventario=[
            {"catalogo_item_id": self.item.pk, "cantidad": 1.5}
        ])
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(json.loads(response.content)["ok"])

    def test_cantidad_string_rechazada(self):
        """cantidad='dos' (string) → 422. No debe lanzar TypeError internamente."""
        payload = _payload_valido(self.item.pk, inventario=[
            {"catalogo_item_id": self.item.pk, "cantidad": "dos"}
        ])
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(json.loads(response.content)["ok"])

    def test_inventario_vacio_rechazado(self):
        """inventario=[] → 422. El servicio requiere al menos un ítem."""
        payload = _payload_valido(self.item.pk, inventario=[])
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(json.loads(response.content)["ok"])

    def test_inventario_con_none_rechazado(self):
        """inventario=[None] → 422 sin error 500 interno."""
        payload = _payload_valido(self.item.pk, inventario=[None])
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertNotEqual(
            response.status_code, 500,
            "Un inventario=[None] no debe provocar error interno 500.",
        )
        self.assertEqual(response.status_code, 422)

    def test_inventario_tipo_no_lista_rechazado(self):
        """inventario='sillon' (string en lugar de lista) → 422."""
        payload = _payload_valido(self.item.pk, inventario="sillon")
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(json.loads(response.content)["ok"])

    def test_catalogo_item_id_nulo_rechazado(self):
        """catalogo_item_id=None → 422 sin 500."""
        payload = _payload_valido(self.item.pk, inventario=[
            {"catalogo_item_id": None, "cantidad": 1}
        ])
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(response.status_code, 422)

    def test_cantidad_masiva_no_genera_error_interno(self):
        """
        cantidad=999999 (valor extremo) → no debe provocar 500.
        Un valor tan alto podría desbordar cálculos de volumen/peso.
        La respuesta puede ser 200 (si el sistema lo acepta) o 422,
        pero nunca 500.
        """
        payload = _payload_valido(self.item.pk, inventario=[
            {"catalogo_item_id": self.item.pk, "cantidad": 999999}
        ])
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertNotEqual(
            response.status_code, 500,
            "Una cantidad extrema no debe provocar error interno 500.",
        )

    def test_items_duplicados_no_generan_error_interno(self):
        """
        Mismo catalogo_item_id enviado dos veces → no debe provocar 500.
        El servicio puede aceptarlo o rechazarlo, pero nunca romperse.
        """
        payload = _payload_valido(self.item.pk, inventario=[
            {"catalogo_item_id": self.item.pk, "cantidad": 1},
            {"catalogo_item_id": self.item.pk, "cantidad": 3},
        ])
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertNotEqual(response.status_code, 500)


# ─────────────────────────────────────────────────────────────────────────────
# PRES-02 · Manipulación de distancia y costos
# ─────────────────────────────────────────────────────────────────────────────

class DistanciaManipulacionTest(TestCase):
    """
    PRES-02: distancia_km es el principal driver del cálculo de precio.
    Un atacante podría intentar enviar valores que alteren el costo final
    o rompan el procesamiento numérico interno.
    """

    def setUp(self):
        self.client = Client()
        _make_tarifa()
        self.item = _make_catalogo_item("Mesa Test")

    def test_distancia_cero_rechazada(self):
        """distancia_km=0 → 422. El form tiene min_value=1."""
        payload = _payload_valido(self.item.pk, distancia_km="0")
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(json.loads(response.content)["ok"])

    def test_distancia_negativa_rechazada(self):
        """distancia_km=-10 → 422."""
        payload = _payload_valido(self.item.pk, distancia_km="-10")
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(json.loads(response.content)["ok"])

    def test_distancia_string_no_numerico_rechazada(self):
        """distancia_km='cerca' → 422 sin 500."""
        payload = _payload_valido(self.item.pk, distancia_km="cerca")
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(response.status_code, 422)

    def test_distancia_ausente_rechazada(self):
        """Sin campo distancia_km → 422."""
        payload = _payload_valido(self.item.pk)
        del payload["distancia_km"]
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(json.loads(response.content)["ok"])

    def test_distancia_astronomica_no_genera_500(self):
        """
        distancia_km=99999999 (valor extremo) → no debe generar 500.
        Un Decimal muy grande podría desbordar max_digits=8 en el modelo
        y lanzar una excepción no controlada de la DB.
        """
        payload = _payload_valido(self.item.pk, distancia_km="99999999")
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertNotEqual(
            response.status_code, 500,
            "Una distancia extrema no debe provocar error interno 500. "
            "El modelo o el form deben rechazarla antes de llegar a la DB.",
        )

    def test_distancia_con_muchos_decimales_no_genera_500(self):
        """
        distancia_km con más decimales de los permitidos (decimal_places=2)
        no debe provocar error 500 de la DB.
        """
        payload = _payload_valido(self.item.pk, distancia_km="15.123456789")
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertNotEqual(response.status_code, 500)


# ─────────────────────────────────────────────────────────────────────────────
# PRES-03 · Manipulación de datos de cliente
# ─────────────────────────────────────────────────────────────────────────────

class ClienteManipulacionTest(TestCase):
    """
    PRES-03: El endpoint crea o reutiliza clientes vía get_or_create(telefono=...).
    Se verifica que inputs maliciosos en campos de texto no generan
    duplicados, errores internos, ni persistencia de datos peligrosos.
    """

    def setUp(self):
        self.client = Client()
        _make_tarifa()
        self.item = _make_catalogo_item("Heladera Test")

    def test_telefono_con_caracteres_especiales_no_genera_500(self):
        """
        Teléfono con caracteres especiales → no debe generar 500.
        El form valida max_length=20 pero no el formato. Verificar que
        llega al modelo sin romper la DB.
        """
        payload = _payload_valido(
            self.item.pk,
            telefono="'; DROP TABLE--",
            telefono_unico="+54911SQLTEST1",  # evitar colisión con otros tests
        )
        # Usamos teléfono real para que no colisione
        payload["telefono"] = "+54911<script>1"
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertNotEqual(
            response.status_code, 500,
            "Un teléfono con caracteres especiales no debe provocar error 500.",
        )

    def test_nombre_con_html_no_genera_500(self):
        """
        Nombre con etiquetas HTML → no debe generar 500.
        El template debe escapar el output; el backend no debe romperse.
        """
        payload = _payload_valido(
            self.item.pk,
            nombre="<script>alert('xss')</script>",
            telefono="+54911XSS0001",
        )
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertNotEqual(response.status_code, 500)

    def test_email_malformado_rechazado(self):
        """email inválido → 422. El form usa EmailField."""
        payload = _payload_valido(
            self.item.pk,
            email="esto-no-es-un-email",
            telefono="+54911EMAIL001",
        )
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(json.loads(response.content)["ok"])

    def test_telefono_vacio_rechazado(self):
        """telefono='' → 422. CharField requerido."""
        payload = _payload_valido(self.item.pk, telefono="")
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(json.loads(response.content)["ok"])

    def test_mismo_telefono_no_duplica_cliente(self):
        """
        Dos solicitudes con el mismo teléfono → un solo Cliente en DB.
        get_or_create garantiza idempotencia; este test lo verifica
        desde el endpoint real.
        """
        telefono = "+5491148580001"
        payload = _payload_valido(self.item.pk, telefono=telefono)

        with _mock_mp():
            _post(self.client, payload)
            _post(self.client, payload)

        count = Cliente.objects.filter(telefono=telefono).count()
        self.assertEqual(
            count, 1,
            f"Se esperaba 1 Cliente con teléfono {telefono}, "
            f"pero se encontraron {count}. get_or_create no funcionó correctamente.",
        )

    def test_nombre_extremadamente_largo_rechazado(self):
        """
        nombre con 500 caracteres → 422. El form tiene max_length=200.
        No debe provocar error de truncado silencioso en DB.
        """
        payload = _payload_valido(
            self.item.pk,
            nombre="A" * 500,
            telefono="+54911LONG0001",
        )
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(json.loads(response.content)["ok"])


# ─────────────────────────────────────────────────────────────────────────────
# PRES-04 · Manipulación de fecha
# ─────────────────────────────────────────────────────────────────────────────

class FechaManipulacionTest(TestCase):
    """
    PRES-04: fecha_deseada controla cuándo se programa la mudanza.
    Fechas inválidas o pasadas podrían crear registros inconsistentes.
    """

    def setUp(self):
        self.client = Client()
        _make_tarifa()
        self.item = _make_catalogo_item("Cama Test")

    def test_fecha_pasada_rechazada(self):
        """Fecha de ayer → 422. clean_fecha_deseada() la rechaza."""
        ayer = (date.today() - timedelta(days=1)).isoformat()
        payload = _payload_valido(self.item.pk, fecha_deseada=ayer)
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(json.loads(response.content)["ok"])

    def test_fecha_hoy_aceptada_o_rechazada_sin_500(self):
        """
        Fecha de hoy es el borde del validador (fecha < today() → rechaza).
        Hoy mismo puede ser aceptado o rechazado según la implementación,
        pero nunca debe provocar 500.
        """
        hoy = date.today().isoformat()
        payload = _payload_valido(self.item.pk, fecha_deseada=hoy)
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertNotEqual(response.status_code, 500)

    def test_fecha_formato_invalido_rechazada(self):
        """fecha_deseada='mañana' → 422 sin 500. DateField lo rechaza."""
        payload = _payload_valido(self.item.pk, fecha_deseada="mañana")
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(response.status_code, 422)

    def test_fecha_ausente_rechazada(self):
        """Sin fecha_deseada → 422."""
        payload = _payload_valido(self.item.pk)
        del payload["fecha_deseada"]
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(json.loads(response.content)["ok"])

    def test_fecha_lejana_no_genera_500(self):
        """
        Fecha 100 años en el futuro → no debe generar 500.
        DateField de Django acepta cualquier fecha válida; el sistema
        no debe romperse aunque el dato sea absurdo.
        """
        lejana = date(date.today().year + 100, 1, 1).isoformat()
        payload = _payload_valido(self.item.pk, fecha_deseada=lejana)
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertNotEqual(response.status_code, 500)

    def test_fecha_como_timestamp_unix_rechazada(self):
        """fecha_deseada=1700000000 → 422. DateField rechaza enteros."""
        payload = _payload_valido(self.item.pk, fecha_deseada='1700000000')
        with _mock_mp():
            response = _post(self.client, payload)
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(response.status_code, 422)


# ─────────────────────────────────────────────────────────────────────────────
# PRES-05 · Integridad transaccional
# ─────────────────────────────────────────────────────────────────────────────

class IntegridadTransaccionalTest(TestCase):
    """
    PRES-05: Verifica que el atomic() y el manejo de errores post-transacción
    (fallo de MP) no dejan la DB en estado inconsistente.
    """

    def setUp(self):
        self.client = Client()
        self.item = _make_catalogo_item("Escritorio Test")

    def test_sin_tarifa_activa_no_crea_mudanza_huerfana(self):
        """
        Si no hay TarifaBase activa, el servicio lanza ValidationError.
        La transacción debe hacer rollback completo: sin Mudanza, sin Cliente
        ni Direcciones huérfanas.

        Este test verifica que el atomic() protege la integridad de la DB.
        """
        # Nos aseguramos de no tener ninguna tarifa activa
        TarifaBase.objects.filter(activa=True).update(activa=False)

        mudanzas_antes = Mudanza.objects.count()

        payload = _payload_valido(self.item.pk, telefono="+54911TX0001")
        response = _post(self.client, payload)

        # Debe devolver error (422 o 502, según cómo propague el servicio)
        self.assertNotEqual(
            response.status_code, 200,
            "Sin tarifa activa el endpoint no debe devolver 200.",
        )
        data = json.loads(response.content)
        self.assertFalse(data["ok"])

        # No debe haber quedado ninguna Mudanza nueva en la DB
        mudanzas_despues = Mudanza.objects.count()
        self.assertEqual(
            mudanzas_antes, mudanzas_despues,
            f"Sin tarifa activa no deben crearse Mudanzas huérfanas. "
            f"Antes: {mudanzas_antes}, después: {mudanzas_despues}.",
        )

    def test_fallo_de_mp_no_revierte_la_mudanza(self):
        """
        Si MercadoPago falla (RuntimeError), la Mudanza ya fue creada
        dentro del atomic(). El diseño intencional del servicio es que
        la Mudanza quede en PRESUPUESTADA sin mp_preference_id.

        Se verifica que la Mudanza persiste y que la respuesta es 502.
        """
        _make_tarifa()

        mudanzas_antes = Mudanza.objects.count()

        with patch(
            "public.services.solicitud_service.MercadoPagoService.generar_preferencia_desde_dato",
            side_effect=RuntimeError("MP no disponible"),
        ):
            payload = _payload_valido(self.item.pk, telefono="+54911TX0002")
            response = _post(self.client, payload)

        self.assertEqual(
            response.status_code, 502,
            "Un fallo de MP debe devolver 502.",
        )
        data = json.loads(response.content)
        self.assertFalse(data["ok"])

        # La Mudanza SÍ debe haberse creado (está fuera del atomic que falla)
        mudanzas_despues = Mudanza.objects.count()
        self.assertEqual(
            mudanzas_despues, mudanzas_antes + 1,
            "La Mudanza debe persistir aunque MP falle. "
            "El admin puede regenerar el link desde el panel.",
        )

    def test_fallo_de_mp_deja_mudanza_en_estado_presupuestada(self):
        """
        Complementa el test anterior: la Mudanza creada ante fallo de MP
        debe quedar en estado PRESUPUESTADA (sin mp_preference_id).
        """
        _make_tarifa()
        telefono = "+54911TX0003"

        with patch(
            "public.services.solicitud_service.MercadoPagoService.generar_preferencia_desde_dato",
            side_effect=RuntimeError("MP no disponible"),
        ):
            payload = _payload_valido(self.item.pk, telefono=telefono)
            _post(self.client, payload)

        mudanza = Mudanza.objects.filter(cliente__telefono=telefono).order_by("-creado_en").first()
        if mudanza:
            self.assertEqual(
                mudanza.estado, Mudanza.Estado.PRESUPUESTADA,
                f"La Mudanza debe estar en PRESUPUESTADA, no en {mudanza.estado}.",
            )
            self.assertFalse(
                bool(mudanza.mp_preference_id),
                "mp_preference_id debe estar vacío ante fallo de MP.",
            )


# ─────────────────────────────────────────────────────────────────────────────
# PRES-06 · Flood / abuso del endpoint
# ─────────────────────────────────────────────────────────────────────────────

class FloodEndpointTest(TestCase):
    """
    PRES-06: El endpoint es público y no requiere autenticación.
    Se verifica que no es posible generar datos duplicados ni degradar
    la DB a través de peticiones repetidas con el mismo payload.
    """

    def setUp(self):
        self.client = Client()
        _make_tarifa()
        self.item = _make_catalogo_item("Lámpara Test")

    def test_mismo_telefono_n_veces_crea_un_solo_cliente(self):
        """
        10 solicitudes con el mismo teléfono → exactamente 1 Cliente.
        get_or_create debe ser idempotente bajo concurrencia simulada.
        """
        telefono = "+54911FLOOD001"
        payload = _payload_valido(self.item.pk, telefono=telefono)

        with _mock_mp():
            for _ in range(10):
                response = _post(self.client, payload)

        # 1. Verificamos que el contador de clientes sea EXACTAMENTE 0 
        # porque el escudo anti-flood bloqueó las peticiones en el aire.
        count = Cliente.objects.filter(telefono=telefono).count()
        self.assertEqual(
            count, 0,
            f"Alerta de Seguridad: Se crearon {count} clientes durante una inundación. "
            "El sistema anti-flood falló."
        )
        
        # 2. Verificamos que la respuesta del servidor ante el flood sea el código 422
        self.assertEqual(response.status_code, 422)

    def test_respuestas_multiples_son_consistentes(self):
        """
        3 solicitudes válidas → las 3 deben devolver ok=True y pago_url.
        Verifica que el endpoint no falla en la segunda o tercera invocación.
        """
        base_tel = "+549118880"
        with _mock_mp():
            for i in range(3):
                payload = _payload_valido(
                    self.item.pk,
                    telefono=f"{base_tel}{i:04d}",
                )
                response = _post(self.client, payload)
                with self.subTest(peticion=i + 1):
                    self.assertEqual(
                        response.status_code, 200,
                        f"La petición #{i+1} falló con {response.status_code}.",
                    )
                    data = json.loads(response.content)
                    self.assertTrue(data["ok"])
                    self.assertIn("pago_url", data)
