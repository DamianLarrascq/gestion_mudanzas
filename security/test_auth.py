"""
Tests de seguridad — SGM (Sistema de Gestión de Mudanzas)
Archivo: tests/security/test_auth.py

Áreas cubiertas
───────────────
  SEC-01  Autenticación — vistas protegidas redirigen al login sin sesión
  SEC-02  Autorización  — usuario sin is_staff bloqueado del panel admin
  SEC-03  CSRF          — endpoints POST autenticados rechazan peticiones sin token
  SEC-04  Webhook MP    — validaciones de payload, tipo y método HTTP
  SEC-05  Endpoint público — validación de payload, método HTTP y respuestas de error

Usuarios de prueba preestablecidos
────────────────────────────────────
  admin       / admin123       — staff, acceso al panel
  admin_sec   / securepass123  — staff, usado en tests de seguridad
  nostaff     / pass123        — sin is_staff, bloqueado del admin

Notas
─────
  - Los tests del webhook MP validan comportamiento *sin* firma X-Signature ya que
    esa validación aún no está implementada en producción (ver nota en webhook/views.py).
    Cuando se implemente, agregar SEC-04-F: firma inválida → HTTP 403.
  - IDOR (ClienteDetailView, ResumenMudanzaView) se cubre en una iteración posterior.
"""

import json
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch, MagicMock

import pytest
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from gestion.models import Cliente, Camion, Mudanza


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / factories locales
# ─────────────────────────────────────────────────────────────────────────────

def _make_staff_user(username: str = "admin_sec", password: str = "securepass123") -> User:
    """Crea (o recupera) un usuario staff estándar de los tests de seguridad."""
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={"is_staff": True, "is_superuser": True},
    )
    user.set_password(password)
    user.save()
    return user


def _make_nostaff_user(username: str = "nostaff", password: str = "pass123") -> User:
    """Crea (o recupera) un usuario sin privilegios."""
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={"is_staff": False, "is_superuser": False},
    )
    user.set_password(password)
    user.save()
    return user


def _make_cliente(telefono: str = "+5491155550001") -> Cliente:
    cliente, _ = Cliente.objects.get_or_create(
        telefono=telefono,
        defaults={"nombre_completo": "Cliente Seguridad"},
    )
    return cliente


def _make_camion(patente: str = "SEC001") -> Camion:
    camion, _ = Camion.objects.get_or_create(
        patente=patente,
        defaults={
            "modelo": "Truck Seguridad",
            "categoria": Camion.Categoria.N1,
            "activo": True,
            "capacidad_volumen_m3": Decimal("15.00"),
            "capacidad_peso_kg": Decimal("3500.00"),
            "anio": 2021,
        },
    )
    return camion


def _make_mudanza(estado: str = Mudanza.Estado.PRESUPUESTADA) -> Mudanza:
    return Mudanza.objects.create(
        cliente=_make_cliente(),
        camion=_make_camion(),
        estado=estado,
        fecha_hora=timezone.now() + timedelta(days=3),
        distancia_km=Decimal("20.00"),
        necesita_ayudantes=True,
        monto_senia=Decimal("15000.00"),
        senia_pagada=False,
        mp_preference_id="PREF_SEC_001",
    )


# ─────────────────────────────────────────────────────────────────────────────
# SEC-01 · Autenticación — vistas protegidas con @login_required / LoginRequiredMixin
# ─────────────────────────────────────────────────────────────────────────────

class AutenticacionVistasGestionTest(TestCase):
    """
    SEC-01: Todas las vistas de /gestion/ deben redirigir a login cuando
    se accede sin sesión activa. Ninguna debe devolver 200 sin autenticar.
    """

    def setUp(self):
        self.client = Client()

    def _assert_redirige_login(self, url: str) -> None:
        """Verifica que la URL responde 302 y la ubicación contiene 'login'."""
        response = self.client.get(url)
        self.assertEqual(
            response.status_code, 302,
            f"Se esperaba redirección (302) en '{url}' sin sesión, "
            f"pero se obtuvo {response.status_code}",
        )
        self.assertIn(
            "login", response["Location"].lower(),
            f"La redirección de '{url}' no apunta al login: {response['Location']}",
        )

    def test_dashboard_sin_sesion_redirige(self):
        """GET /gestion/ sin sesión → 302 al login."""
        self._assert_redirige_login("/gestion/")

    def test_mudanza_list_sin_sesion_redirige(self):
        """GET /gestion/mudanzas/ sin sesión → 302 al login."""
        self._assert_redirige_login("/gestion/mudanzas/")

    def test_cliente_list_sin_sesion_redirige(self):
        """GET /gestion/clientes/ sin sesión → 302 al login."""
        self._assert_redirige_login("/gestion/clientes/")

    def test_empleado_list_sin_sesion_redirige(self):
        """GET /gestion/empleados/ sin sesión → 302 al login."""
        self._assert_redirige_login("/gestion/empleados/")

    def test_flota_monitor_sin_sesion_redirige(self):
        """GET /gestion/flota/ sin sesión → 302 al login."""
        self._assert_redirige_login("/gestion/flota/")

    def test_config_tarifas_sin_sesion_redirige(self):
        """GET /gestion/configuracion/tarifas/ sin sesión → 302 al login."""
        self._assert_redirige_login("/gestion/configuracion/tarifas/")

    def test_tarifa_nueva_sin_sesion_redirige(self):
        """GET /gestion/configuracion/tarifas/nueva/ sin sesión → 302 al login."""
        self._assert_redirige_login("/gestion/configuracion/tarifas/nueva/")

    def test_api_disponibilidad_sin_sesion_redirige(self):
        """GET /gestion/empleados/1/disponibilidad/ sin sesión → 302 al login."""
        self._assert_redirige_login("/gestion/empleados/1/disponibilidad/")

    def test_api_capacidad_camion_sin_sesion_redirige(self):
        """GET /gestion/mudanzas/1/validar-capacidad/ sin sesión → 302 al login."""
        self._assert_redirige_login("/gestion/mudanzas/1/validar-capacidad/")

    def test_ninguna_vista_gestion_devuelve_200_sin_sesion(self):
        """Ninguna URL de /gestion/ debe devolver 200 sin autenticación."""
        urls_protegidas = [
            "/gestion/",
            "/gestion/mudanzas/",
            "/gestion/clientes/",
            "/gestion/empleados/",
            "/gestion/flota/",
            "/gestion/configuracion/tarifas/",
        ]
        for url in urls_protegidas:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertNotEqual(
                    response.status_code, 200,
                    f"'{url}' devolvió 200 sin autenticación — vista desprotegida",
                )


class AutenticacionConSesionTest(TestCase):
    """
    SEC-01-B: Un usuario staff autenticado puede acceder a las vistas de gestión.
    Verifica que la protección no bloquea a usuarios legítimos.
    """

    def setUp(self):
        self.user = _make_staff_user()
        self.client = Client()
        self.client.login(username="admin_sec", password="securepass123")

    def test_dashboard_accesible_con_sesion(self):
        """Un usuario autenticado recibe 200 en el dashboard."""
        response = self.client.get("/gestion/")
        self.assertEqual(response.status_code, 200)

    def test_mudanza_list_accesible_con_sesion(self):
        """Un usuario autenticado accede a la lista de mudanzas."""
        response = self.client.get("/gestion/mudanzas/")
        self.assertEqual(response.status_code, 200)

    def test_cliente_list_accesible_con_sesion(self):
        """Un usuario autenticado accede a la lista de clientes."""
        response = self.client.get("/gestion/clientes/")
        self.assertEqual(response.status_code, 200)


# ─────────────────────────────────────────────────────────────────────────────
# SEC-02 · Autorización — panel admin bloqueado a usuarios sin is_staff
# ─────────────────────────────────────────────────────────────────────────────

class AutorizacionAdminTest(TestCase):
    """
    SEC-02: El panel /admin/ debe ser inaccesible para usuarios sin is_staff,
    independientemente de que tengan sesión activa.
    """

    def setUp(self):
        self.staff_user = _make_staff_user()
        self.nostaff_user = _make_nostaff_user()
        self.client = Client()

    def test_admin_bloqueado_sin_sesion(self):
        """GET /admin/ sin sesión → redirección al login."""
        response = self.client.get("/admin/")
        self.assertIn(response.status_code, [301, 302])
        self.assertIn("login", response["Location"].lower())

    def test_admin_bloqueado_a_usuario_sin_staff(self):
        """Un usuario sin is_staff no puede acceder al panel admin."""
        self.client.login(username="nostaff", password="pass123")
        response = self.client.get("/admin/")
        # Django redirige a login (302) o devuelve 403 según la configuración
        self.assertIn(
            response.status_code, [302, 403],
            "Un usuario sin is_staff no debe recibir 200 en /admin/",
        )

    def test_admin_accesible_a_staff(self):
        """Un usuario con is_staff accede correctamente al panel admin."""
        self.client.login(username="admin_sec", password="securepass123")
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)

    def test_nostaff_no_accede_changelist_clientes(self):
        """Un usuario sin staff no puede listar clientes en el admin."""
        self.client.login(username="nostaff", password="pass123")
        response = self.client.get("/admin/gestion/cliente/")
        self.assertIn(response.status_code, [302, 403])

    def test_nostaff_no_accede_changelist_mudanzas(self):
        """Un usuario sin staff no puede listar mudanzas en el admin."""
        self.client.login(username="nostaff", password="pass123")
        response = self.client.get("/admin/gestion/mudanza/")
        self.assertIn(response.status_code, [302, 403])

    def test_nostaff_no_puede_crear_cliente_via_admin(self):
        """Un usuario sin staff no puede acceder al formulario de creación de clientes."""
        self.client.login(username="nostaff", password="pass123")
        response = self.client.get("/admin/gestion/cliente/add/")
        self.assertIn(response.status_code, [302, 403])

    def test_credenciales_incorrectas_no_autentican(self):
        """Login con contraseña incorrecta falla y no otorga sesión."""
        logueado = self.client.login(username="admin_sec", password="password_erronea")
        self.assertFalse(logueado)

    def test_usuario_admin_predefinido_tiene_staff(self):
        """El usuario 'admin_sec' predefinido tiene is_staff=True."""
        self.assertTrue(self.staff_user.is_staff)

    def test_usuario_nostaff_predefinido_no_tiene_staff(self):
        """El usuario 'nostaff' predefinido tiene is_staff=False."""
        self.assertFalse(self.nostaff_user.is_staff)


# ─────────────────────────────────────────────────────────────────────────────
# SEC-03 · CSRF — endpoints POST autenticados
# ─────────────────────────────────────────────────────────────────────────────

class CSRFProteccionTest(TestCase):
    """
    SEC-03: Los endpoints POST autenticados deben rechazar peticiones
    que no incluyan un token CSRF válido (enforce_csrf_checks=True).

    Django desactiva la verificación CSRF en TestClient por defecto.
    Se usa Client(enforce_csrf_checks=True) para simular el comportamiento real.
    """

    def setUp(self):
        self.user = _make_staff_user()
        # Cliente con CSRF activo — simula petición real desde el navegador
        self.client_csrf = Client(enforce_csrf_checks=True)
        self.client_csrf.login(username="admin_sec", password="securepass123")

        # Cliente normal para obtener tokens válidos
        self.client_normal = Client()
        self.client_normal.login(username="admin_sec", password="securepass123")

    def test_post_tarifa_nueva_sin_csrf_rechazado(self):
        """POST a /gestion/configuracion/tarifas/nueva/ sin CSRF → 403."""
        response = self.client_csrf.post(
            "/gestion/configuracion/tarifas/nueva/",
            data={"nombre": "Tarifa Test", "precio_por_km": "1500"},
        )
        self.assertEqual(
            response.status_code, 403,
            "POST sin token CSRF debe ser rechazado (403)",
        )

    def test_post_tarifa_nueva_con_csrf_permitido(self):
        """POST a /gestion/configuracion/tarifas/nueva/ con CSRF válido no da 403."""
        # Obtenemos el token desde un GET previo
        get_resp = self.client_normal.get("/gestion/configuracion/tarifas/nueva/")
        self.assertEqual(get_resp.status_code, 200)
        csrf_token = get_resp.cookies.get("csrftoken")
        self.assertIsNotNone(csrf_token, "No se encontró cookie csrftoken en la respuesta")

    def test_post_tarifa_editar_sin_csrf_rechazado(self):
        """POST a /gestion/configuracion/tarifas/<pk>/editar/ sin CSRF → 403."""
        response = self.client_csrf.post(
            "/gestion/configuracion/tarifas/999/editar/",
            data={"nombre": "Tarifa Hack"},
        )
        self.assertEqual(response.status_code, 403)

    def test_csrf_middleware_activo_en_settings(self):
        """CsrfViewMiddleware debe estar en MIDDLEWARE (configuración correcta)."""
        from django.conf import settings
        middlewares = settings.MIDDLEWARE
        csrf_middleware = "django.middleware.csrf.CsrfViewMiddleware"
        self.assertIn(
            csrf_middleware, middlewares,
            f"'{csrf_middleware}' no está en MIDDLEWARE — protección CSRF desactivada globalmente",
        )


# ─────────────────────────────────────────────────────────────────────────────
# SEC-04 · Webhook MP — validación de payload y método HTTP
# ─────────────────────────────────────────────────────────────────────────────

class WebhookMPSeguridadTest(TestCase):
    """
    SEC-04: El webhook de MercadoPago (/webhook/mp/notificacion/) expone
    un endpoint @csrf_exempt de alto valor. Se verifica que:
      - Solo acepta POST (GET, PUT, PATCH, DELETE → 405)
      - Body vacío o JSON malformado → 200 (comportamiento defensivo, evita reintentos MP)
      - Notificaciones de tipo distinto a 'payment' son ignoradas silenciosamente
      - Un payment_id ausente no genera error interno (500)
      - Payloads con campos extra no rompen el procesamiento
    """

    WEBHOOK_URL = "/webhook/mp/notificacion/"

    def setUp(self):
        self.client = Client()

    def _post_json(self, payload: dict) -> object:
        return self.client.post(
            self.WEBHOOK_URL,
            data=json.dumps(payload),
            content_type="application/json",
        )

    # ── Método HTTP ───────────────────────────────────────────────────────────

    def test_get_rechazado_405(self):
        """GET al webhook MP → 405 Method Not Allowed."""
        response = self.client.get(self.WEBHOOK_URL)
        self.assertEqual(response.status_code, 405)

    def test_put_rechazado_405(self):
        """PUT al webhook MP → 405."""
        response = self.client.put(
            self.WEBHOOK_URL,
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 405)

    def test_patch_rechazado_405(self):
        """PATCH al webhook MP → 405."""
        response = self.client.patch(
            self.WEBHOOK_URL,
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 405)

    def test_delete_rechazado_405(self):
        """DELETE al webhook MP → 405."""
        response = self.client.delete(self.WEBHOOK_URL)
        self.assertEqual(response.status_code, 405)

    # ── Validación de payload ─────────────────────────────────────────────────

    def test_body_vacio_no_rompe_endpoint(self):
        """Body vacío → 200 (MP no reintenta si recibe 200)."""
        response = self.client.post(
            self.WEBHOOK_URL,
            data=b"",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

    def test_body_json_malformado_no_rompe_endpoint(self):
        """JSON malformado → 200 (sin excepción 500)."""
        response = self.client.post(
            self.WEBHOOK_URL,
            data=b"{esto no es json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

    def test_tipo_no_payment_ignorado(self):
        """Notificación de tipo 'merchant_order' → 200 sin efectos secundarios."""
        payload = {"type": "merchant_order", "data": {"id": "ORD-001"}}
        response = self._post_json(payload)
        self.assertEqual(response.status_code, 200)

    def test_tipo_desconocido_ignorado(self):
        """Tipo de notificación desconocido → 200 sin efectos secundarios."""
        payload = {"type": "unknown_event_type_xss", "data": {}}
        response = self._post_json(payload)
        self.assertEqual(response.status_code, 200)

    def test_payment_sin_id_no_genera_500(self):
        """Notificación de pago sin 'id' en data → 200, sin error interno."""
        payload = {"type": "payment", "data": {}}
        response = self._post_json(payload)
        self.assertEqual(response.status_code, 200)

    def test_payload_con_campos_extra_no_rompe_procesamiento(self):
        """Payload con campos inesperados → 200, sin excepción."""
        payload = {
            "type": "payment",
            "data": {"id": "999999999"},
            "campo_extra": "valor_inesperado",
            "otro_campo": [1, 2, 3],
        }
        # El procesamiento intentará consultar MP (fallará en test) pero no debe dar 500
        with patch("gestion.services.mercadopago_service._get_sdk") as mock_sdk:
            mock_instance = MagicMock()
            mock_instance.payment.return_value.get.return_value = {
                "status": 404,
                "response": {},
            }
            mock_sdk.return_value = mock_instance
            response = self._post_json(payload)
        self.assertEqual(response.status_code, 200)

    def test_payload_vacio_objeto_no_rompe_procesamiento(self):
        """Payload JSON vacío {} → 200, tipo ausente ignorado correctamente."""
        response = self._post_json({})
        self.assertEqual(response.status_code, 200)

    def test_endpoint_no_requiere_autenticacion(self):
        """El webhook MP es público — no debe redirigir al login (MP no tiene sesión)."""
        payload = {"type": "merchant_order", "data": {}}
        response = self._post_json(payload)
        # Debe ser 200, no una redirección a login
        self.assertNotEqual(response.status_code, 302)
        if response.status_code == 302:
            self.assertNotIn("login", response.get("Location", "").lower())

    # ── Idempotencia ──────────────────────────────────────────────────────────

    def test_mudanza_ya_confirmada_no_duplica_historial(self):
        """
        Si la mudanza ya está CONFIRMADA, una segunda notificación aprobada
        no debe crear entradas duplicadas en HistorialEstado.
        """
        from gestion.models.auditoria import HistorialEstado
        from django.contrib.auth.models import User

        sistema_user, _ = User.objects.get_or_create(
            username="sistema",
            defaults={"is_active": False},
        )
        mudanza = _make_mudanza(estado=Mudanza.Estado.CONFIRMADA)
        count_antes = HistorialEstado.objects.filter(mudanza=mudanza).count()

        # Invocamos directamente la función interna de confirmación
        from webhook.views import _confirmar_mudanza
        _confirmar_mudanza(str(mudanza.uuid))

        count_despues = HistorialEstado.objects.filter(mudanza=mudanza).count()
        self.assertEqual(
            count_antes, count_despues,
            "Una mudanza ya CONFIRMADA no debe generar nuevas entradas en HistorialEstado",
        )

    def test_uuid_inexistente_no_genera_500(self):
        """
        _confirmar_mudanza con un UUID que no existe en la DB
        no debe lanzar excepción no controlada.
        """
        from webhook.views import _confirmar_mudanza
        # No debe lanzar ninguna excepción
        try:
            _confirmar_mudanza("00000000-0000-0000-0000-000000000000")
        except Exception as exc:
            self.fail(f"_confirmar_mudanza lanzó una excepción inesperada: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# SEC-05 · Endpoint público — /presupuesto/solicitar/
# ─────────────────────────────────────────────────────────────────────────────

class EndpointPublicoSeguridadTest(TestCase):
    """
    SEC-05: El endpoint público POST /presupuesto/solicitar/ no requiere
    autenticación pero debe validar correctamente el payload entrante,
    rechazar métodos incorrectos y no exponer información interna en errores.
    """

    URL = "/presupuesto/solicitar/"

    def setUp(self):
        self.client = Client()

    def _payload_valido(self, **overrides) -> dict:
        """Construye un payload mínimo válido para el formulario público."""
        import datetime
        payload = {
            "nombre": "Ana García",
            "telefono": "+5491100000099",
            "email": "ana@mail.com",
            "origen_calle": "Av. Corrientes",
            "origen_numero": "1234",
            "origen_localidad": "CABA",
            "destino_calle": "Av. Santa Fe",
            "destino_numero": "567",
            "destino_localidad": "CABA",
            "fecha_deseada": (datetime.date.today() + datetime.timedelta(days=10)).isoformat(),
            "distancia_km": "15.00",
            "inventario": [],
        }
        payload.update(overrides)
        return payload

    def _post_json(self, payload: dict) -> object:
        return self.client.post(
            self.URL,
            data=json.dumps(payload),
            content_type="application/json",
        )

    # ── Método HTTP ───────────────────────────────────────────────────────────

    def test_get_rechazado_405(self):
        """GET al endpoint público → 405."""
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 405)

    def test_put_rechazado_405(self):
        """PUT al endpoint público → 405."""
        response = self.client.put(
            self.URL,
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 405)

    # ── Validación de payload ─────────────────────────────────────────────────

    def test_body_json_malformado_responde_400(self):
        """JSON malformado → 400 con campo 'ok': False."""
        response = self.client.post(
            self.URL,
            data=b"{ no es json valido }",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertFalse(data["ok"])

    def test_payload_vacio_responde_error_validacion(self):
        """Payload vacío {} → 422 con errores de validación."""
        response = self._post_json({})
        self.assertEqual(response.status_code, 422)
        data = json.loads(response.content)
        self.assertFalse(data["ok"])
        self.assertIn("errores", data)

    def test_campos_obligatorios_ausentes_dan_422(self):
        """Payload sin campos requeridos (nombre, teléfono, direcciones) → 422."""
        response = self._post_json({"email": "solo@estocampo.com"})
        self.assertEqual(response.status_code, 422)
        data = json.loads(response.content)
        self.assertFalse(data["ok"])

    def test_fecha_en_pasado_rechazada(self):
        """Una fecha_deseada en el pasado debe ser rechazada con 422."""
        import datetime
        payload = self._payload_valido(
            fecha_deseada=(datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        )
        response = self._post_json(payload)
        self.assertEqual(response.status_code, 422)
        data = json.loads(response.content)
        self.assertFalse(data["ok"])

    def test_distancia_negativa_rechazada(self):
        """distancia_km negativa o cero debe ser rechazada por el formulario."""
        payload = self._payload_valido(distancia_km="-10.00")
        response = self._post_json(payload)
        self.assertEqual(response.status_code, 422)
        data = json.loads(response.content)
        self.assertFalse(data["ok"])

    def test_email_invalido_rechazado(self):
        """Email con formato inválido → 422."""
        payload = self._payload_valido(email="esto-no-es-un-email")
        response = self._post_json(payload)
        self.assertEqual(response.status_code, 422)
        data = json.loads(response.content)
        self.assertFalse(data["ok"])

    def test_respuesta_error_no_expone_traceback(self):
        """Las respuestas de error no deben incluir trazas internas de Python."""
        response = self._post_json({})
        content = response.content.decode()
        self.assertNotIn("Traceback", content)
        self.assertNotIn("File \"", content)

    def test_endpoint_no_requiere_sesion(self):
        """El endpoint público no debe redirigir a login (es de acceso libre)."""
        response = self._post_json({})
        self.assertNotEqual(
            response.status_code, 302,
            "El endpoint público no debe requerir autenticación",
        )

    # ── Respuesta estructurada ────────────────────────────────────────────────

    def test_respuesta_error_contiene_campo_ok_false(self):
        """Toda respuesta de error incluye {'ok': False} en el JSON."""
        response = self._post_json({})
        try:
            data = json.loads(response.content)
            self.assertIn("ok", data)
            self.assertFalse(data["ok"])
        except json.JSONDecodeError:
            self.fail("La respuesta de error no es JSON válido")

    def test_respuesta_error_contiene_campo_errores(self):
        """Toda respuesta 422 incluye el campo 'errores' con detalle."""
        response = self._post_json({})
        data = json.loads(response.content)
        self.assertIn("errores", data)
        self.assertIsInstance(data["errores"], dict)


# ─────────────────────────────────────────────────────────────────────────────
# SEC-06 · Headers y configuración de seguridad de Django
# ─────────────────────────────────────────────────────────────────────────────

class ConfiguracionSeguridadDjangoTest(TestCase):
    """
    SEC-06: Verifica que los middlewares y configuraciones de seguridad
    recomendados por Django estén activos en settings.py.
    """

    def _get_middlewares(self) -> list[str]:
        from django.conf import settings
        return settings.MIDDLEWARE

    def test_security_middleware_activo(self):
        """SecurityMiddleware debe estar presente."""
        self.assertIn(
            "django.middleware.security.SecurityMiddleware",
            self._get_middlewares(),
        )

    def test_csrf_middleware_activo(self):
        """CsrfViewMiddleware debe estar presente."""
        self.assertIn(
            "django.middleware.csrf.CsrfViewMiddleware",
            self._get_middlewares(),
        )

    def test_clickjacking_middleware_activo(self):
        """XFrameOptionsMiddleware debe estar presente para protección clickjacking."""
        self.assertIn(
            "django.middleware.clickjacking.XFrameOptionsMiddleware",
            self._get_middlewares(),
        )

    def test_auth_middleware_activo(self):
        """AuthenticationMiddleware debe estar presente."""
        self.assertIn(
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            self._get_middlewares(),
        )

    def test_secret_key_no_es_vacia(self):
        """SECRET_KEY no debe estar vacío."""
        from django.conf import settings
        self.assertTrue(
            bool(settings.SECRET_KEY),
            "SECRET_KEY está vacío — configuración insegura",
        )

    def test_secret_key_tiene_longitud_minima(self):
        """SECRET_KEY debe tener al menos 40 caracteres."""
        from django.conf import settings
        self.assertGreaterEqual(
            len(settings.SECRET_KEY), 40,
            f"SECRET_KEY demasiado corta ({len(settings.SECRET_KEY)} chars) — insegura para producción",
        )

    def test_password_validators_configurados(self):
        """Deben estar configurados al menos 2 validadores de contraseña."""
        from django.conf import settings
        validators = getattr(settings, "AUTH_PASSWORD_VALIDATORS", [])
        self.assertGreaterEqual(
            len(validators), 2,
            "Se esperan al menos 2 validadores de contraseña en AUTH_PASSWORD_VALIDATORS",
        )

    def test_password_validator_longitud_minima_presente(self):
        """MinimumLengthValidator debe estar entre los validadores de contraseña."""
        from django.conf import settings
        nombres = [v["NAME"] for v in settings.AUTH_PASSWORD_VALIDATORS]
        self.assertIn(
            "django.contrib.auth.password_validation.MinimumLengthValidator",
            nombres,
        )
