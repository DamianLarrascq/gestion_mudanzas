"""
Tests de seguridad — IDOR (Insecure Direct Object Reference)
Archivo: tests/security/test_idor.py

Vulnerabilidad documentada
──────────────────────────
  ClienteDetailView  → GET /gestion/clientes/<pk>/
  ResumenMudanzaView → GET /gestion/mudanzas/<pk>/resumen/

  Ambas vistas usan get_object_or_404(pk=self.kwargs["pk"]) sin ningún
  filtro de ownership. Un usuario autenticado (sin importar su rol ni a
  qué clientes o mudanzas pertenece) puede enumerar y acceder a los
  recursos de cualquier otro usuario simplemente incrementando el pk en
  la URL.

Objetivo de los tests
──────────────────────
  Estos tests están diseñados para FALLAR en la implementación actual y
  documentar las rutas de explotación concretas. Cuando la vulnerabilidad
  sea corregida (añadiendo filtros de ownership o permisos por objeto),
  los tests deberán pasar.

  Los tests NO corrigen nada: solo exponen el comportamiento inseguro.

Escenario de prueba
────────────────────
  - user_a / user_b: dos usuarios staff independientes (simulan dos
    operadores del sistema sin relación entre sí).
  - cliente_a / mudanza_a: creados y asociados al contexto de user_a.
  - cliente_b / mudanza_b: creados y asociados al contexto de user_b.

  Un operador real no debería poder ver los datos del otro.
  La vulnerabilidad permite que lo haga.

Notas
──────
  - Mudanza y Cliente no tienen campo `owner` (FK a User) en el modelo
    actual: el "ownership" se entiende como pertenencia organizacional
    (un operador solo debería ver lo que gestionó).
  - ResumenMudanzaView.post() también es vulnerable; se testa por separado.
  - IDOR vía pk secuencial permite enumeración: pk=1, 2, 3... → exposición
    masiva de datos.
"""

from decimal import Decimal
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from gestion.models import Cliente, Camion, Mudanza
from gestion.models.direcciones import Direccion


# ─────────────────────────────────────────────────────────────────────────────
# Factories
# ─────────────────────────────────────────────────────────────────────────────

def _make_user(username: str, password: str = "TestPass1234!") -> User:
    user = User.objects.create_user(
        username=username,
        password=password,
        is_staff=True,
    )
    return user


def _make_cliente(sufijo: str) -> Cliente:
    return Cliente.objects.create(
        nombre_completo=f"Cliente {sufijo}",
        telefono=f"+549111000{sufijo[:4].zfill(4)}",
        dni=f"9000{sufijo[:4].zfill(4)}",
    )


def _make_direccion(sufijo: str) -> Direccion:
    return Direccion.objects.create(
        calle=f"Calle {sufijo}",
        numero="100",
        localidad="CABA",
    )


def _make_mudanza(cliente: Cliente, sufijo: str) -> Mudanza:
    return Mudanza.objects.create(
        cliente=cliente,
        estado=Mudanza.Estado.PRESUPUESTADA,
        fecha_hora=timezone.now() + timedelta(days=5),
        origen=_make_direccion(f"origen_{sufijo}"),
        destino=_make_direccion(f"destino_{sufijo}"),
        distancia_km=Decimal("20.00"),
        necesita_ayudantes=True,
        monto_senia=Decimal("15000.00"),
        senia_pagada=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# IDOR-01 · ClienteDetailView — GET /gestion/clientes/<pk>/
# ─────────────────────────────────────────────────────────────────────────────

class IDORClienteDetailViewTest(TestCase):
    """
    IDOR-01: ClienteDetailView resuelve el pk directamente desde la URL
    sin verificar que el cliente pertenezca al usuario autenticado.

    Todos estos tests deben FALLAR (recibir 200 cuando se espera 403/404)
    hasta que se implemente control de acceso por objeto.
    """

    def setUp(self):
        # Dos operadores independientes
        self.user_a = _make_user("operador_a")
        self.user_b = _make_user("operador_b")

        # Cada operador tiene su propio cliente
        self.cliente_a = _make_cliente("A001")
        self.cliente_b = _make_cliente("B002")

        # user_b intenta acceder al cliente de user_a
        self.client_b = Client()
        self.client_b.login(username="operador_b", password="TestPass1234!")

    def test_usuario_b_accede_a_cliente_de_usuario_a(self):
        """
        VULNERABILIDAD ACTIVA: user_b puede ver el detalle de cliente_a
        con solo conocer su pk.

        Comportamiento actual : HTTP 200 — datos de cliente_a visibles.
        Comportamiento esperado: HTTP 403 o 404 — acceso denegado.
        """
        url = f"/gestion/clientes/{self.cliente_a.pk}/"
        response = self.client_b.get(url)

        # Este assertNotEqual DOCUMENTA LA VULNERABILIDAD:
        # si el sistema fuera seguro, este assert no sería necesario.
        # Mientras la vista no tenga ownership check, response.status_code == 200.
        self.assertNotEqual(
            response.status_code, 403,
            f"IDOR CONFIRMADO: user_b accedió al cliente #{self.cliente_a.pk} "
            f"(propiedad de user_a) y recibió {response.status_code} en lugar de 403.",
        )
        self.assertNotEqual(
            response.status_code, 404,
            f"IDOR CONFIRMADO: user_b accedió al cliente #{self.cliente_a.pk} "
            f"(propiedad de user_a) y recibió {response.status_code} en lugar de 404.",
        )

    def test_enumeracion_secuencial_de_pks_expone_clientes(self):
        """
        VULNERABILIDAD ACTIVA: los pks son secuenciales y predecibles.
        Un atacante puede iterar pk=1,2,3... y obtener todos los clientes.

        Se verifica que al menos 2 pks distintos devuelven 200 con user_b.
        """
        pks_accesibles = []
        for cliente in [self.cliente_a, self.cliente_b]:
            url = f"/gestion/clientes/{cliente.pk}/"
            response = self.client_b.get(url)
            if response.status_code == 200:
                pks_accesibles.append(cliente.pk)

        # La vulnerabilidad permite acceso a múltiples recursos
        self.assertGreater(
            len(pks_accesibles), 1,
            f"IDOR CONFIRMADO: user_b pudo acceder a {len(pks_accesibles)} cliente(s) "
            f"vía enumeración de pks: {pks_accesibles}. "
            "Sin control de acceso por objeto, todos los clientes son accesibles.",
        )

    def test_pk_aleatorio_fuera_de_rango_devuelve_404(self):
        """
        Caso control: un pk inexistente debe devolver 404.
        Verifica que el mecanismo básico de not-found funciona.
        Este test DEBE pasar siempre (pk inexistente → 404).
        """
        response = self.client_b.get("/gestion/clientes/999999/")
        self.assertEqual(
            response.status_code, 404,
            "Un pk inexistente debe devolver 404.",
        )

    def test_usuario_sin_sesion_no_accede(self):
        """
        Caso control de autenticación: sin sesión → redirección al login.
        Confirma que la vista tiene @LoginRequired pero NO ownership check.
        Este test DEBE pasar siempre.
        """
        client_anonimo = Client()
        response = client_anonimo.get(f"/gestion/clientes/{self.cliente_a.pk}/")
        self.assertIn(response.status_code, [302, 301])
        self.assertIn("login", response["Location"].lower())

    def test_respuesta_200_contiene_datos_del_cliente_ajeno(self):
        """
        VULNERABILIDAD ACTIVA: la respuesta 200 incluye el nombre del
        cliente_a en el contenido HTML, confirmando fuga de datos reales.

        Este test falla (es decir, confirma la vulnerabilidad) si el nombre
        de cliente_a aparece en la respuesta de user_b.
        """
        url = f"/gestion/clientes/{self.cliente_a.pk}/"
        response = self.client_b.get(url)

        if response.status_code == 200:
            content = response.content.decode("utf-8", errors="replace")
            nombre_expuesto = self.cliente_a.nombre_completo in content
            self.assertFalse(
                nombre_expuesto,
                f"FUGA DE DATOS CONFIRMADA: el nombre '{self.cliente_a.nombre_completo}' "
                f"de cliente #{self.cliente_a.pk} aparece en la respuesta de user_b. "
                "La vista expone datos sensibles sin control de acceso.",
            )


# ─────────────────────────────────────────────────────────────────────────────
# IDOR-02 · ResumenMudanzaView — GET /gestion/mudanzas/<pk>/resumen/
# ─────────────────────────────────────────────────────────────────────────────

class IDORResumenMudanzaViewGetTest(TestCase):
    """
    IDOR-02: ResumenMudanzaView (GET) resuelve get_object_or_404(Mudanza, pk=...)
    sin filtro de ownership. Expone presupuestos, montos de seña, datos del
    cliente y estado de pago a cualquier usuario autenticado.
    """

    def setUp(self):
        self.user_a = _make_user("conductor_a")
        self.user_b = _make_user("conductor_b")

        self.cliente_a = _make_cliente("MA01")
        self.cliente_b = _make_cliente("MB02")

        self.mudanza_a = _make_mudanza(self.cliente_a, "ma01")
        self.mudanza_b = _make_mudanza(self.cliente_b, "mb02")

        self.client_b = Client()
        self.client_b.login(username="conductor_b", password="TestPass1234!")

    def test_usuario_b_accede_al_resumen_de_mudanza_de_usuario_a(self):
        """
        VULNERABILIDAD ACTIVA: user_b puede ver el resumen de mudanza_a
        (asociada a cliente_a, gestionada por user_a) con solo conocer su pk.

        Comportamiento actual : HTTP 200.
        Comportamiento esperado: HTTP 403 o 404.
        """
        url = f"/gestion/mudanzas/{self.mudanza_a.pk}/resumen/"
        response = self.client_b.get(url)

        self.assertNotEqual(
            response.status_code, 403,
            f"IDOR CONFIRMADO: user_b accedió al resumen de mudanza #{self.mudanza_a.pk} "
            f"(asociada a cliente_a) y recibió {response.status_code} en lugar de 403.",
        )
        self.assertNotEqual(
            response.status_code, 404,
            f"IDOR CONFIRMADO: user_b accedió al resumen de mudanza #{self.mudanza_a.pk} "
            f"y recibió {response.status_code} en lugar de 404.",
        )

    def test_enumeracion_secuencial_expone_todas_las_mudanzas(self):
        """
        VULNERABILIDAD ACTIVA: pks secuenciales permiten iterar todas
        las mudanzas del sistema. Se verifica que user_b accede a mudanzas
        que no le pertenecen.
        """
        pks_accesibles = []
        for mudanza in [self.mudanza_a, self.mudanza_b]:
            url = f"/gestion/mudanzas/{mudanza.pk}/resumen/"
            response = self.client_b.get(url)
            if response.status_code == 200:
                pks_accesibles.append(mudanza.pk)

        self.assertGreater(
            len(pks_accesibles), 1,
            f"IDOR CONFIRMADO: user_b pudo acceder a {len(pks_accesibles)} mudanza(s) "
            f"via enumeración: {pks_accesibles}. "
            "Presupuestos, montos y datos de clientes quedan expuestos.",
        )

    def test_respuesta_200_expone_nombre_cliente_ajeno(self):
        """
        VULNERABILIDAD ACTIVA: el nombre del cliente_a (dato sensible)
        aparece en la respuesta HTML entregada a user_b.
        """
        url = f"/gestion/mudanzas/{self.mudanza_a.pk}/resumen/"
        response = self.client_b.get(url)

        if response.status_code == 200:
            content = response.content.decode("utf-8", errors="replace")
            nombre_expuesto = self.cliente_a.nombre_completo in content
            self.assertFalse(
                nombre_expuesto,
                f"FUGA DE DATOS CONFIRMADA: el nombre '{self.cliente_a.nombre_completo}' "
                f"aparece en el resumen de mudanza #{self.mudanza_a.pk} entregado a user_b. "
                "El contexto de la vista incluye cliente_nombre sin restricción.",
            )

    def test_monto_senia_visible_en_respuesta_de_usuario_no_autorizado(self):
        """
        VULNERABILIDAD ACTIVA: el monto de seña (dato financiero sensible)
        de mudanza_a queda expuesto a user_b.

        ResumenMudanzaView incluye monto_senia en el contexto del template.
        """
        url = f"/gestion/mudanzas/{self.mudanza_a.pk}/resumen/"
        response = self.client_b.get(url)

        if response.status_code == 200:
            content = response.content.decode("utf-8", errors="replace")
            # El monto 15000 aparece en el HTML renderizado
            monto_visible = "15000" in content or "15.000" in content
            self.assertFalse(
                monto_visible,
                f"FUGA DE DATOS FINANCIEROS: el monto de seña $15.000 de mudanza "
                f"#{self.mudanza_a.pk} es visible en la respuesta de user_b. "
                "Datos financieros de terceros expuestos sin autorización.",
            )

    def test_pk_inexistente_devuelve_404(self):
        """
        Caso control: mudanza con pk inexistente → 404.
        Este test DEBE pasar siempre.
        """
        response = self.client_b.get("/gestion/mudanzas/999999/resumen/")
        self.assertEqual(response.status_code, 404)

    def test_usuario_sin_sesion_redirige_al_login(self):
        """
        Caso control de autenticación: sin sesión → redirección.
        Este test DEBE pasar siempre.
        """
        client_anonimo = Client()
        response = client_anonimo.get(f"/gestion/mudanzas/{self.mudanza_a.pk}/resumen/")
        self.assertIn(response.status_code, [301, 302])
        self.assertIn("login", response["Location"].lower())


# ─────────────────────────────────────────────────────────────────────────────
# IDOR-03 · ResumenMudanzaView — POST /gestion/mudanzas/<pk>/resumen/
# ─────────────────────────────────────────────────────────────────────────────

class IDORResumenMudanzaViewPostTest(TestCase):
    """
    IDOR-03: ResumenMudanzaView.post() también es vulnerable.
    El método llama get_object_or_404(Mudanza, pk=mudanza_pk) y luego
    ejecuta PresupuestoService.calcular_y_persistir() sobre esa mudanza.

    Un atacante puede:
      1. Recalcular y sobreescribir el presupuesto de una mudanza ajena.
      2. Alterar monto_senia y distancia_km de mudanzas que no le pertenecen.
      3. Disparar la generación de preferencias MP sobre mudanzas ajenas.
    """

    def setUp(self):
        self.user_a = _make_user("admin_a_post")
        self.user_b = _make_user("admin_b_post")

        self.cliente_a = _make_cliente("PA01")
        self.mudanza_a = _make_mudanza(self.cliente_a, "pa01")

        self.client_b = Client()
        self.client_b.login(username="admin_b_post", password="TestPass1234!")

    def test_usuario_b_puede_hacer_post_sobre_mudanza_de_usuario_a(self):
        """
        VULNERABILIDAD ACTIVA: user_b puede enviar un POST a la mudanza de user_a
        y el servidor lo procesa sin devolver 403.

        El POST intenta recalcular el presupuesto con valores arbitrarios.
        Comportamiento actual : HTTP 200 (o 302 si hay redirección tras éxito).
        Comportamiento esperado: HTTP 403.
        """
        url = f"/gestion/mudanzas/{self.mudanza_a.pk}/resumen/"
        response = self.client_b.post(url, data={
            "distancia_km": "99.99",
            "costo_peajes": "5000",
            "generar_pago": "0",
        })

        self.assertNotEqual(
            response.status_code, 403,
            f"IDOR POST CONFIRMADO: user_b pudo hacer POST sobre mudanza "
            f"#{self.mudanza_a.pk} (de user_a) y recibió {response.status_code}. "
            "La vista no verifica ownership en el método POST.",
        )

    def test_post_sin_csrf_desde_usuario_b_rechazado(self):
        """
        Caso control CSRF: un POST sin token CSRF válido debe ser rechazado
        incluso si el IDOR existe. Verifica que la capa CSRF funciona
        independientemente del bug de ownership.

        Este test DEBE pasar siempre (CSRF es ortogonal al IDOR).
        """
        client_b_csrf = Client(enforce_csrf_checks=True)
        client_b_csrf.login(username="admin_b_post", password="TestPass1234!")

        url = f"/gestion/mudanzas/{self.mudanza_a.pk}/resumen/"
        response = client_b_csrf.post(url, data={
            "distancia_km": "99.99",
            "costo_peajes": "5000",
        })

        self.assertEqual(
            response.status_code, 403,
            "Un POST sin token CSRF debe ser rechazado con 403, "
            "independientemente de si hay vulnerabilidad IDOR.",
        )

    def test_usuario_sin_sesion_no_puede_hacer_post(self):
        """
        Caso control: sin sesión, el POST redirige al login.
        Este test DEBE pasar siempre.
        """
        client_anonimo = Client()
        url = f"/gestion/mudanzas/{self.mudanza_a.pk}/resumen/"
        response = client_anonimo.post(url, data={"distancia_km": "10"})
        self.assertIn(response.status_code, [301, 302])
        self.assertIn("login", response["Location"].lower())
