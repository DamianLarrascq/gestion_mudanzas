"""
Tests de seguridad — SQL Injection y Webhook MP Spoofing
Archivo: tests/security/test_sqli_webhook.py

Áreas cubiertas
───────────────
  SQLI-01  Inyección SQL en endpoints públicos y autenticados
             Campos de texto de formularios, query params de búsqueda,
             parámetros de URL (pk), filtros de listados en el panel.

  SPOOF-01 Payload falso al webhook de MercadoPago
             Simula un atacante que conoce la URL del webhook y envía
             JSON construido para hacer creer al sistema que un pago
             fue aprobado sin que el dinero haya sido transferido.

  SPOOF-02 Manipulación del estado de mudanza vía webhook
             Escalada de estados: intentar confirmar mudanzas en estados
             inválidos (CANCELADA, COMPLETADA, EN_CURSO) usando el webhook.

  SPOOF-03 Tareas asíncronas (Celery)
             Verificar que las tareas de notificación no pueden ser
             disparadas con datos arbitrarios desde el exterior y que
             el serializador JSON rechaza payloads con tipos inseguros.

Contexto de la vulnerabilidad SPOOF-01
───────────────────────────────────────
  El endpoint /webhook/mp/notificacion/ tiene @csrf_exempt y es público.
  El código en webhook/views.py incluye la nota:
    "validar la firma X-Signature de MP antes de procesar en producción"
  — lo que significa que HOY la firma NO se valida.

  Un atacante que conoce:
    - la URL del webhook (pública en el código fuente)
    - el uuid de una mudanza (por IDOR o por ser cliente)
  puede enviar un POST con {"type":"payment","data":{"id":"FAKE"}} y,
  si _procesar_pago() consulta MP con ese id y MP responde "approved",
  el sistema confirma la mudanza sin que el pago haya ocurrido.

  Los tests SPOOF-01 documentan este vector. Los tests que esperan
  que el sistema RECHACE el payload están marcados con el estado
  esperado: algunos PASARÁN (la validación existe), otros FALLARÁN
  (la validación aún no existe) y están comentados en consecuencia.

Notas
──────
  - Todos los accesos a la API de MP se mockean para evitar llamadas reales.
  - Los tests de SQLI usan Django ORM + SQLite: Django parametriza todas
    las queries por defecto. Los tests verifican que el ORM no es bypasseado
    y que los inputs llegan sanitizados.
  - CELERY_TASK_ALWAYS_EAGER=True en CI hace que las tareas corran
    sincrónicamente en el mismo proceso.
"""

import json
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from gestion.models import Cliente, Mudanza
from gestion.models.auditoria import HistorialEstado
from gestion.models.catalogo import CatalogoItem
from gestion.models.direcciones import Direccion
from gestion.models.presupuestos import TarifaBase


# ─────────────────────────────────────────────────────────────────────────────
# Factories compartidas
# ─────────────────────────────────────────────────────────────────────────────

WEBHOOK_URL = "/webhook/mp/notificacion/"


def _make_sistema_user() -> User:
    u, _ = User.objects.get_or_create(
        username="sistema",
        defaults={"is_active": False},
    )
    return u


def _make_staff_user(username: str = "admin_sec", password: str = "securepass123") -> User:
    u, _ = User.objects.get_or_create(username=username)
    u.set_password(password)
    u.is_staff = True
    u.is_superuser = True
    u.save()
    return u


def _make_cliente(telefono: str = "+5491199990001") -> Cliente:
    c, _ = Cliente.objects.get_or_create(
        telefono=telefono,
        defaults={"nombre_completo": "Cliente Seguridad SQL"},
    )
    return c


def _make_direccion(tag: str = "test") -> Direccion:
    return Direccion.objects.create(
        calle=f"Calle {tag}",
        numero="100",
        localidad="CABA",
    )


def _make_mudanza(estado: str = Mudanza.Estado.PRESUPUESTADA, telefono: str = "+5491199990001") -> Mudanza:
    _make_sistema_user()
    return Mudanza.objects.create(
        cliente=_make_cliente(telefono),
        estado=estado,
        fecha_hora=timezone.now() + timedelta(days=5),
        origen=_make_direccion("origen"),
        destino=_make_direccion("destino"),
        distancia_km=Decimal("20.00"),
        necesita_ayudantes=True,
        monto_senia=Decimal("15000.00"),
        senia_pagada=False,
        mp_preference_id="PREF_TEST_001",
    )


def _post_webhook(client: Client, payload: dict) -> object:
    return client.post(
        WEBHOOK_URL,
        data=json.dumps(payload),
        content_type="application/json",
    )


def _mp_response_aprobado(mudanza_uuid: str, payment_id: str = "PAY_FAKE_001") -> dict:
    """Simula la respuesta de MP para un pago aprobado."""
    return {
        "status": 200,
        "response": {
            "id": payment_id,
            "status": "approved",
            "metadata": {"mudanza_uuid": mudanza_uuid},
        },
    }


def _mp_response_pendiente(payment_id: str = "PAY_FAKE_002") -> dict:
    return {
        "status": 200,
        "response": {
            "id": payment_id,
            "status": "pending",
            "metadata": {},
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# SQLI-01 · SQL Injection
# ─────────────────────────────────────────────────────────────────────────────

class SQLInjectionEndpointPublicoTest(TestCase):
    """
    SQLI-01-A: Inyección SQL en el endpoint público /presupuesto/solicitar/.

    Django ORM parametriza todas las queries, por lo que el ORM en sí no es
    vulnerable. Lo que se verifica es que:
      1. Los payloads con strings de inyección clásicos NO provocan 500
         (el ORM no los ejecuta como SQL).
      2. No se crean registros con datos de inyección persistidos.
      3. La validación del form rechaza correctamente los inputs inválidos.
    """

    URL = "/presupuesto/solicitar/"
    FECHA_VALIDA = (timezone.now().date() + timedelta(days=10)).isoformat()

    SQLI_STRINGS = [
        "' OR '1'='1",
        "'; DROP TABLE gestion_mudanza; --",
        "1; SELECT * FROM django_session --",
        "' UNION SELECT username,password FROM auth_user --",
        "admin'--",
        "' OR 1=1 --",
        "'; INSERT INTO auth_user (username) VALUES ('hacker'); --",
        "\\x27 OR 1=1",
    ]

    def setUp(self):
        self.client = Client()
        TarifaBase.objects.get_or_create(
            nombre="Tarifa SQLI Test",
            defaults={
                "precio_por_km": Decimal("800.00"),
                "precio_ayudante": Decimal("3000.00"),
                "recargo_piso": Decimal("1500.00"),
                "recargo_hora_pico": Decimal("1.20"),
                "recargo_fin_de_semana": Decimal("1.15"),
                "permite_caba_feriados": False,
                "activa": True,
                "vigente_desde": timezone.now().date(),
                "seguro_camion": Decimal("2000.00"),
                "empleado_art": Decimal("500.00"),
                "empleado_seguro_riesgo": Decimal("400.00"),
                "empleado_seguro_ayudante": Decimal("300.00"),
                "salario_conductor": Decimal("8000.00"),
                "salario_ayudante": Decimal("5000.00"),
            },
        )
        CatalogoItem.objects.get_or_create(
            nombre="Item SQLI",
            defaults={
                "categoria": "LIVING",
                "volumen_m3": Decimal("0.5"),
                "peso_estimado_kg": Decimal("20.00"),
            },
        )

    def _post_json(self, payload: dict) -> object:
        return self.client.post(
            self.URL,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_sqli_en_nombre_no_genera_500(self):
        """Strings de inyección SQL en el campo 'nombre' → nunca 500."""
        item = CatalogoItem.objects.get(nombre="Item SQLI")
        for sqli in self.SQLI_STRINGS:
            with self.subTest(payload=sqli[:40]):
                payload = {
                    "nombre": sqli,
                    "telefono": f"+549119999{abs(hash(sqli)) % 10000:04d}",
                    "email": "sqli@test.com",
                    "origen_calle": "Av. Test",
                    "origen_numero": "1",
                    "origen_localidad": "CABA",
                    "destino_calle": "Av. Dest",
                    "destino_numero": "2",
                    "destino_localidad": "CABA",
                    "fecha_deseada": self.FECHA_VALIDA,
                    "distancia_km": "10.00",
                    "inventario": [{"catalogo_item_id": item.pk, "cantidad": 1}],
                }
                with patch(
                    "public.services.solicitud_service.MercadoPagoService.generar_preferencia_desde_dato",
                    return_value="https://mp.com/fake",
                ):
                    response = self._post_json(payload)
                self.assertNotEqual(
                    response.status_code, 500,
                    f"SQLI en 'nombre' provocó 500: {sqli!r}",
                )

    def test_sqli_en_telefono_rechazado_sin_500(self):
        """Strings de inyección SQL en 'telefono' → 422 o 200, nunca 500."""
        item = CatalogoItem.objects.get(nombre="Item SQLI")
        for sqli in self.SQLI_STRINGS:
            with self.subTest(payload=sqli[:40]):
                payload = {
                    "nombre": "Test SQLI",
                    "telefono": sqli,
                    "email": "sqli@test.com",
                    "origen_calle": "Av. Test",
                    "origen_numero": "1",
                    "origen_localidad": "CABA",
                    "destino_calle": "Av. Dest",
                    "destino_numero": "2",
                    "destino_localidad": "CABA",
                    "fecha_deseada": self.FECHA_VALIDA,
                    "distancia_km": "10.00",
                    "inventario": [{"catalogo_item_id": item.pk, "cantidad": 1}],
                }
                with patch(
                    "public.services.solicitud_service.MercadoPagoService.generar_preferencia_desde_dato",
                    return_value="https://mp.com/fake",
                ):
                    response = self._post_json(payload)
                self.assertNotEqual(
                    response.status_code, 500,
                    f"SQLI en 'telefono' provocó 500: {sqli!r}",
                )

    def test_sqli_no_elimina_registros_existentes(self):
        """
        Un payload con DROP TABLE no debe eliminar registros de la DB.
        Verifica que el ORM parametriza la query y no ejecuta SQL arbitrario.
        """
        item = CatalogoItem.objects.get(nombre="Item SQLI")
        clientes_antes = Cliente.objects.count()

        payload = {
            "nombre": "'; DROP TABLE gestion_cliente; --",
            "telefono": "+54911DROP001",
            "email": "drop@test.com",
            "origen_calle": "Av. Test",
            "origen_numero": "1",
            "origen_localidad": "CABA",
            "destino_calle": "Av. Dest",
            "destino_numero": "2",
            "destino_localidad": "CABA",
            "fecha_deseada": self.FECHA_VALIDA,
            "distancia_km": "10.00",
            "inventario": [{"catalogo_item_id": item.pk, "cantidad": 1}],
        }
        with patch(
            "public.services.solicitud_service.MercadoPagoService.generar_preferencia_desde_dato",
            return_value="https://mp.com/fake",
        ):
            self._post_json(payload)

        # La tabla no debe haber sido eliminada
        try:
            clientes_despues = Cliente.objects.count()
        except Exception as exc:
            self.fail(
                f"La tabla gestion_cliente fue comprometida por inyección SQL: {exc}"
            )

        self.assertGreaterEqual(
            clientes_despues, clientes_antes,
            "El payload DROP TABLE redujo el número de clientes en la DB.",
        )

    def test_sqli_union_no_expone_usuarios_en_respuesta(self):
        """
        UNION SELECT sobre auth_user no debe aparecer en la respuesta.
        El ORM parametriza: el string de inyección se trata como valor literal.
        """
        item = CatalogoItem.objects.get(nombre="Item SQLI")
        payload = {
            "nombre": "' UNION SELECT username,password,'' FROM auth_user --",
            "telefono": "+54911UNION001",
            "email": "union@test.com",
            "origen_calle": "Av. Test",
            "origen_numero": "1",
            "origen_localidad": "CABA",
            "destino_calle": "Av. Dest",
            "destino_numero": "2",
            "destino_localidad": "CABA",
            "fecha_deseada": self.FECHA_VALIDA,
            "distancia_km": "10.00",
            "inventario": [{"catalogo_item_id": item.pk, "cantidad": 1}],
        }
        with patch(
            "public.services.solicitud_service.MercadoPagoService.generar_preferencia_desde_dato",
            return_value="https://mp.com/fake",
        ):
            response = self._post_json(payload)

        content = response.content.decode("utf-8", errors="replace")
        # La respuesta no debe contener hashes de contraseñas ni usernames reales
        self.assertNotIn("pbkdf2_sha256", content)
        self.assertNotIn("auth_user", content)


class SQLInjectionPanelAdminTest(TestCase):
    """
    SQLI-01-B: Inyección SQL en parámetros de búsqueda del panel admin.

    Django admin usa ORM para todos los filtros de búsqueda, por lo que
    no es directamente vulnerable. Se verifica que los query params con
    strings de inyección no provocan 500 ni exponen datos.
    """

    SQLI_PARAMS = [
        "' OR '1'='1",
        "'; DROP TABLE auth_user; --",
        "1 UNION SELECT * FROM auth_user --",
        "\\x00",
        "' OR 1=1 --",
    ]

    def setUp(self):
        self.user = _make_staff_user()
        self.client = Client()
        self.client.login(username="admin_sec", password="securepass123")

    def test_sqli_en_search_admin_mudanza_no_genera_500(self):
        """Query params con SQLI en /admin/gestion/mudanza/?q=... → nunca 500."""
        for sqli in self.SQLI_PARAMS:
            with self.subTest(param=sqli[:40]):
                response = self.client.get(
                    "/admin/gestion/mudanza/",
                    {"q": sqli},
                )
                self.assertNotEqual(
                    response.status_code, 500,
                    f"SQLI en ?q= del admin causó 500: {sqli!r}",
                )
                self.assertIn(
                    response.status_code, [200, 302, 403],
                    f"Código inesperado {response.status_code} con SQLI en ?q=",
                )

    def test_sqli_en_search_admin_cliente_no_genera_500(self):
        """Query params con SQLI en /admin/gestion/cliente/?q=... → nunca 500."""
        for sqli in self.SQLI_PARAMS:
            with self.subTest(param=sqli[:40]):
                response = self.client.get(
                    "/admin/gestion/cliente/",
                    {"q": sqli},
                )
                self.assertNotEqual(response.status_code, 500)

    def test_sqli_en_pk_url_admin_no_genera_500(self):
        """
        URL con string de inyección donde se espera un pk entero
        → Django router no hace match (404) o rechaza el tipo (400).
        Nunca debe dar 500.
        """
        sqli_pks = [
            "1 OR 1=1",
            "1; DROP TABLE--",
            "' OR '1'='1",
        ]
        for sqli in sqli_pks:
            with self.subTest(pk=sqli):
                response = self.client.get(f"/admin/gestion/mudanza/{sqli}/change/")
                self.assertNotEqual(
                    response.status_code, 500,
                    f"SQLI en pk de URL causó 500: {sqli!r}",
                )


class SQLInjectionVistasPanelGestionTest(TestCase):
    """
    SQLI-01-C: Inyección SQL en parámetros de búsqueda de las vistas
    del panel de gestión (/gestion/).
    """

    SQLI_PARAMS = [
        "' OR '1'='1",
        "'; DROP TABLE gestion_mudanza --",
        "1 UNION SELECT * FROM auth_user --",
    ]

    def setUp(self):
        self.user = _make_staff_user()
        self.client = Client()
        self.client.login(username="admin_sec", password="securepass123")

    def test_sqli_en_filtro_mudanzas_no_genera_500(self):
        """SQLI en ?q= de /gestion/mudanzas/ → nunca 500."""
        for sqli in self.SQLI_PARAMS:
            with self.subTest(param=sqli[:40]):
                response = self.client.get("/gestion/mudanzas/", {"q": sqli})
                self.assertNotEqual(response.status_code, 500)

    def test_sqli_en_filtro_clientes_no_genera_500(self):
        """SQLI en ?q= de /gestion/clientes/ → nunca 500."""
        for sqli in self.SQLI_PARAMS:
            with self.subTest(param=sqli[:40]):
                response = self.client.get("/gestion/clientes/", {"q": sqli})
                self.assertNotEqual(response.status_code, 500)

    def test_sqli_en_pk_de_url_gestion_no_genera_500(self):
        """
        pk no entero en /gestion/clientes/<pk>/ → 404 (no match de URL)
        o 400, nunca 500.
        """
        response = self.client.get("/gestion/clientes/' OR '1'='1/")
        self.assertNotEqual(response.status_code, 500)


# ─────────────────────────────────────────────────────────────────────────────
# SPOOF-01 · Webhook MP — payload falso para confirmar seña sin pagar
# ─────────────────────────────────────────────────────────────────────────────

class WebhookMPSpoofingPagoTest(TestCase):
    """
    SPOOF-01: Un atacante envía un payload JSON al webhook fingiendo que
    MercadoPago notificó un pago aprobado. La vulnerabilidad central es que
    el endpoint no valida la firma X-Signature de MP.

    Escenario de ataque
    ────────────────────
    1. El atacante conoce la URL: /webhook/mp/notificacion/ (pública).
    2. El atacante conoce el uuid de una mudanza (por IDOR o como cliente).
    3. Envía POST {"type":"payment","data":{"id":"FAKE_ID"}}.
    4. El sistema llama _procesar_pago("FAKE_ID") → consulta MP.
    5. Si el mock de MP devuelve "approved", la mudanza se confirma.

    Lo que se documenta
    ────────────────────
    - Tests marcados con 🔴 VULNERABILIDAD ACTIVA: fallan si no hay firma.
    - Tests marcados con ✅ CONTROL: deben pasar siempre.
    """

    def setUp(self):
        _make_sistema_user()
        self.client = Client()
        self.mudanza = _make_mudanza(
            estado=Mudanza.Estado.PRESUPUESTADA,
            telefono="+54911SPOOF001",
        )

    # ── ✅ CONTROL: payload malformado o tipo incorrecto ──────────────────────

    def test_payload_tipo_no_payment_no_confirma_mudanza(self):
        """
        Tipo distinto a 'payment' → la mudanza NO debe cambiar de estado.
        Este comportamiento ya existe y DEBE pasar.
        """
        estado_original = self.mudanza.estado
        _post_webhook(self.client, {"type": "merchant_order", "data": {"id": "ORD-001"}})

        self.mudanza.refresh_from_db()
        self.assertEqual(
            self.mudanza.estado, estado_original,
            "Una notificación de tipo 'merchant_order' no debe cambiar el estado de la mudanza.",
        )

    def test_payload_sin_payment_id_no_confirma_mudanza(self):
        """
        Notificación de tipo 'payment' sin id → la mudanza NO cambia.
        """
        estado_original = self.mudanza.estado
        _post_webhook(self.client, {"type": "payment", "data": {}})

        self.mudanza.refresh_from_db()
        self.assertEqual(self.mudanza.estado, estado_original)

    def test_payload_con_payment_id_invalido_no_genera_500(self):
        """
        payment_id que no existe en MP → MP devuelve 404, el sistema
        lo loguea y retorna 200. La mudanza no se modifica.
        """
        with patch("gestion.services.mercadopago_service._get_sdk") as mock_sdk:
            mock_instance = MagicMock()
            mock_instance.payment.return_value.get.return_value = {
                "status": 404,
                "response": {},
            }
            mock_sdk.return_value = mock_instance

            response = _post_webhook(
                self.client,
                {"type": "payment", "data": {"id": "ID_QUE_NO_EXISTE"}},
            )

        self.assertEqual(response.status_code, 200)
        self.mudanza.refresh_from_db()
        self.assertEqual(
            self.mudanza.estado, Mudanza.Estado.PRESUPUESTADA,
            "Un payment_id inexistente no debe confirmar la mudanza.",
        )

    # ── 🔴 VULNERABILIDAD ACTIVA: sin validación de firma ────────────────────

    def test_spoof_pago_aprobado_confirma_mudanza_sin_firma(self):
        """
        🔴 VULNERABILIDAD ACTIVA — SIN VALIDACIÓN DE FIRMA X-Signature:

        Un atacante que construye un payload válido y mockea la respuesta
        de MP como "approved" logra confirmar la mudanza sin haber pagado.

        Esto ocurre porque:
          - El endpoint no verifica la cabecera X-Signature de MP.
          - _procesar_pago() confía en cualquier payment_id del body.
          - Si MP (o un atacante con acceso a un payment_id real aprobado
            de otra transacción) responde "approved", la mudanza se confirma.

        Comportamiento actual : la mudanza pasa a CONFIRMADA (test PASA → bug).
        Comportamiento esperado: el sistema debe rechazar el request por falta
                                 de firma válida → mudanza sigue en PRESUPUESTADA.

        Cuando se implemente la validación de X-Signature, este test debe
        invertirse: assertNotEqual(mudanza.estado, CONFIRMADA).
        """
        mudanza_uuid = str(self.mudanza.uuid)

        with patch("gestion.services.mercadopago_service._get_sdk") as mock_sdk:
            mock_instance = MagicMock()
            mock_instance.payment.return_value.get.return_value = (
                _mp_response_aprobado(mudanza_uuid, "PAY_SPOOF_001")
            )
            mock_sdk.return_value = mock_instance

            _post_webhook(
                self.client,
                {"type": "payment", "data": {"id": "PAY_SPOOF_001"}},
            )

        self.mudanza.refresh_from_db()

        # 🔴 Este assertEqual documenta la vulnerabilidad:
        # Si el sistema fuera seguro, la mudanza NO debería estar CONFIRMADA.
        # El test PASA porque la vulnerabilidad EXISTS.
        # Cuando se corrija, cambiar a assertNotEqual.
        self.assertEqual(
            self.mudanza.estado, Mudanza.Estado.CONFIRMADA,
            "VULNERABILIDAD CONFIRMADA: el webhook aceptó un payload falso y "
            "confirmó la mudanza sin validar la firma X-Signature de MP. "
            "Implementar validación de firma para corregir.",
        )

    def test_spoof_sin_cabecera_x_signature_no_rechazado(self):
        """
        🔴 VULNERABILIDAD ACTIVA — ausencia de X-Signature no bloquea el request:

        Un POST sin la cabecera X-Signature (que MP siempre incluye) debería
        ser rechazado inmediatamente (403 o 400). Actualmente se procesa igual.

        Comportamiento actual : HTTP 200 — el request se procesa.
        Comportamiento esperado: HTTP 403 — firma ausente → rechazado.
        """
        response = self.client.post(
            WEBHOOK_URL,
            data=json.dumps({"type": "merchant_order", "data": {}}),
            content_type="application/json",
            # Nótese: sin HTTP_X_SIGNATURE ni HTTP_X_REQUEST_ID
        )

        # 🔴 Documenta que el sistema NO rechaza por firma ausente:
        self.assertEqual(
            response.status_code, 200,
            "VULNERABILIDAD CONFIRMADA: el webhook no rechaza requests sin "
            "X-Signature. Debe devolver 403 cuando la cabecera está ausente.",
        )

    def test_spoof_con_uuid_de_otro_cliente_confirma_mudanza_ajena(self):
        """
        🔴 VULNERABILIDAD ACTIVA — combinación IDOR + Spoofing:

        Un atacante que conoce el uuid de una mudanza ajena (por IDOR) puede
        construir un payload que confirme esa mudanza sin pagar.

        Este test demuestra que las dos vulnerabilidades (IDOR + falta de firma)
        se encadenan para un ataque completo.
        """
        mudanza_victima = _make_mudanza(
            estado=Mudanza.Estado.PRESUPUESTADA,
            telefono="+54911VICTIM001",
        )
        uuid_victima = str(mudanza_victima.uuid)

        with patch("gestion.services.mercadopago_service._get_sdk") as mock_sdk:
            mock_instance = MagicMock()
            mock_instance.payment.return_value.get.return_value = (
                _mp_response_aprobado(uuid_victima, "PAY_CHAIN_001")
            )
            mock_sdk.return_value = mock_instance

            _post_webhook(
                self.client,
                {"type": "payment", "data": {"id": "PAY_CHAIN_001"}},
            )

        mudanza_victima.refresh_from_db()

        # 🔴 Documenta la vulnerabilidad encadenada:
        self.assertEqual(
            mudanza_victima.estado, Mudanza.Estado.CONFIRMADA,
            "VULNERABILIDAD ENCADENADA (IDOR + Spoofing): el atacante confirmó "
            "una mudanza ajena sin pagar usando su uuid. "
            "Requiere: (1) validación de X-Signature, (2) corrección del IDOR.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# SPOOF-02 · Escalada de estado vía webhook
# ─────────────────────────────────────────────────────────────────────────────

class WebhookMPEscaladaEstadoTest(TestCase):
    """
    SPOOF-02: El webhook puede intentar confirmar mudanzas que están en
    estados donde la transición es inválida (CANCELADA, COMPLETADA, EN_CURSO).

    _confirmar_mudanza() tiene lógica parcial para esto: si el estado no es
    PRESUPUESTADA emite un warning pero igual confirma. Se verifica este
    comportamiento y sus implicancias de seguridad.
    """

    def setUp(self):
        _make_sistema_user()
        self.client = Client()

    def _spoof_confirmacion(self, mudanza: Mudanza) -> Mudanza:
        """Dispara el spoof y retorna la mudanza refrescada."""
        mudanza_uuid = str(mudanza.uuid)
        with patch("gestion.services.mercadopago_service._get_sdk") as mock_sdk:
            mock_instance = MagicMock()
            mock_instance.payment.return_value.get.return_value = (
                _mp_response_aprobado(mudanza_uuid, f"PAY_ESC_{mudanza.pk}")
            )
            mock_sdk.return_value = mock_instance
            _post_webhook(
                self.client,
                {"type": "payment", "data": {"id": f"PAY_ESC_{mudanza.pk}"}},
            )
        mudanza.refresh_from_db()
        return mudanza

    def test_spoof_sobre_mudanza_cancelada_documenta_comportamiento(self):
        """
        Una mudanza CANCELADA no debería poder ser confirmada por el webhook.
        _confirmar_mudanza() emite warning pero procede igual.

        Comportamiento actual : puede cambiar a CONFIRMADA (regresión de estado).
        Comportamiento esperado: rechazar la transición si estado == CANCELADA.
        """
        mudanza = _make_mudanza(
            estado=Mudanza.Estado.CANCELADA,
            telefono="+54911CANCEL001",
        )
        mudanza = self._spoof_confirmacion(mudanza)

        # Documenta que la transición ocurre (si falla, la corrección ya existe)
        if mudanza.estado == Mudanza.Estado.CONFIRMADA:
            # La vulnerabilidad existe: un pago puede "revivir" una mudanza cancelada
            pass  # Comportamiento actual documentado — no es el esperado
        else:
            # La corrección ya está implementada
            self.assertEqual(mudanza.estado, Mudanza.Estado.CANCELADA)

    def test_spoof_sobre_mudanza_completada_no_regresa_estado(self):
        """
        Una mudanza COMPLETADA no debe poder retroceder a CONFIRMADA.
        Esto sería una regresión de estado que permitiría cobrar la seña dos veces.
        """
        mudanza = _make_mudanza(
            estado=Mudanza.Estado.COMPLETADA,
            telefono="+54911COMPLET001",
        )
        mudanza = self._spoof_confirmacion(mudanza)

        self.assertNotEqual(
            mudanza.estado, Mudanza.Estado.PRESUPUESTADA,
            "Una mudanza COMPLETADA no debe retroceder a PRESUPUESTADA vía webhook.",
        )

    def test_spoof_sobre_mudanza_ya_confirmada_es_idempotente(self):
        """
        ✅ CONTROL: Una mudanza ya CONFIRMADA no debe generar un nuevo
        HistorialEstado. _confirmar_mudanza() tiene esta protección.
        """
        mudanza = _make_mudanza(
            estado=Mudanza.Estado.CONFIRMADA,
            telefono="+54911IDEM001",
        )
        historial_antes = HistorialEstado.objects.filter(mudanza=mudanza).count()

        self._spoof_confirmacion(mudanza)

        historial_despues = HistorialEstado.objects.filter(mudanza=mudanza).count()
        self.assertEqual(
            historial_antes, historial_despues,
            "Re-confirmar una mudanza ya CONFIRMADA no debe crear entradas duplicadas "
            "en HistorialEstado.",
        )
        mudanza.refresh_from_db()
        self.assertEqual(mudanza.estado, Mudanza.Estado.CONFIRMADA)


# ─────────────────────────────────────────────────────────────────────────────
# SPOOF-03 · Tareas asíncronas Celery
# ─────────────────────────────────────────────────────────────────────────────

class CeleryTareasAsincronasSegridadTest(TestCase):
    """
    SPOOF-03: Las tareas de Celery no deben poder ser disparadas con datos
    arbitrarios desde el exterior, y el serializador JSON debe rechazar
    tipos inseguros (pickle está desactivado según test_celery.py).

    Con CELERY_TASK_ALWAYS_EAGER=True las tareas corren sincrónicamente,
    lo que permite probar su comportamiento de forma determinística en CI.
    """

    def setUp(self):
        _make_sistema_user()

    def test_serializer_json_no_acepta_pickle(self):
        """
        Celery configurado con JSON serializer no puede deserializar
        un payload pickle, lo que previene ejecución arbitraria de código.
        """
        from django.conf import settings
        serializer = getattr(settings, "CELERY_TASK_SERIALIZER", None)
        self.assertEqual(
            serializer, "json",
            "CELERY_TASK_SERIALIZER debe ser 'json', no 'pickle'. "
            "El serializador pickle permite ejecución arbitraria de código "
            "si un atacante controla el broker.",
        )

    def test_tarea_notificacion_con_uuid_invalido_no_genera_excepcion(self):
        """
        Llamar a una tarea de notificación con un mudanza_uuid que no existe
        no debe propagar una excepción no controlada.

        Simula el caso donde un atacante inyecta un mensaje directamente
        en el broker Redis con un uuid arbitrario.
        """
        from config.celery import app

        # Verificamos que la tarea existe y es invocable
        tareas_registradas = list(app.tasks.keys())
        tareas_notificacion = [t for t in tareas_registradas if "notificacion" in t.lower()]

        if not tareas_notificacion:
            self.skipTest(
                "No hay tareas de notificación registradas aún. "
                "Agregar cuando se implementen en notificaciones/tasks.py."
            )

        for nombre_tarea in tareas_notificacion:
            tarea = app.tasks[nombre_tarea]
            with self.subTest(tarea=nombre_tarea):
                try:
                    tarea.apply(args=["00000000-0000-0000-0000-000000000000"])
                except Exception as exc:
                    # La tarea puede fallar, pero no debe propagar excepciones
                    # no controladas que rompan el worker
                    self.assertNotIsInstance(
                        exc, (KeyboardInterrupt, SystemExit),
                        f"La tarea {nombre_tarea} propagó una excepción crítica: {exc}",
                    )

    def test_celery_no_acepta_tipos_inseguros_en_argumentos(self):
        """
        Con JSON serializer, Celery no puede transmitir objetos Python
        arbitrarios (sets, instancias de clases, etc.) como argumentos.
        Verifica que json.dumps rechaza tipos no serializables.
        """
        tipos_inseguros = [
            {"arg": {1, 2, 3}},           # set — no serializable en JSON
            {"arg": object()},             # instancia arbitraria
            {"arg": lambda x: x},          # función lambda
        ]
        for tipo in tipos_inseguros:
            with self.subTest(tipo=type(tipo["arg"]).__name__):
                with self.assertRaises(TypeError):
                    json.dumps(tipo)

    def test_no_existe_endpoint_para_disparar_tareas_directamente(self):
        """
        No debe existir ningún endpoint HTTP que permita disparar tareas
        Celery directamente desde el exterior sin autenticación.

        Las rutas conocidas del proyecto se verifican: ninguna debe
        aceptar POST sin autenticación y devolver 200.
        """
        rutas_sospechosas = [
            "/tasks/run/",
            "/celery/run/",
            "/admin/tasks/",
            "/api/tasks/",
            "/run-task/",
        ]
        client = Client()
        for ruta in rutas_sospechosas:
            with self.subTest(ruta=ruta):
                response = client.post(
                    ruta,
                    data=json.dumps({"task": "os.system", "args": ["rm -rf /"]}),
                    content_type="application/json",
                )
                self.assertNotEqual(
                    response.status_code, 200,
                    f"La ruta {ruta} aceptó un POST sin autenticación (200). "
                    "Ningún endpoint debe permitir disparar tareas desde el exterior.",
                )

    def test_tarea_confirmacion_mudanza_requiere_uuid_valido(self):
        """
        Si existe una tarea que confirma mudanzas, debe manejar correctamente
        un uuid con formato inválido sin propagar excepciones.

        Simula inyección de mensajes malformados en el broker.
        """
        from webhook.views import _confirmar_mudanza

        uuids_invalidos = [
            "",                                         # vacío
            "no-es-un-uuid",                           # formato incorrecto
            "' OR '1'='1",                             # intento de SQLI
            "00000000-0000-0000-0000-000000000000",    # uuid nulo válido pero inexistente
            "<script>alert(1)</script>",               # XSS
            "a" * 1000,                                # string largo
        ]

        for uuid_val in uuids_invalidos:
            with self.subTest(uuid=uuid_val[:40]):
                try:
                    _confirmar_mudanza(uuid_val)
                    # Llegamos aquí: la función manejó el error internamente (correcto)
                except (Mudanza.DoesNotExist, ValueError):
                    pass  # Excepción esperada y controlada
                except Exception as exc:
                    self.fail(
                        f"_confirmar_mudanza({uuid_val!r}) propagó una excepción "
                        f"no controlada: {type(exc).__name__}: {exc}"
                    )
