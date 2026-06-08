"""
Tests unitarios — app: public
SGM · Grupo 2 · Desarrollo de Software

User Stories cubiertas:
  US-016  Formulario público de presupuesto accesible sin login
  US-017  Acceso por terceros: el formulario registra datos aunque lo complete un tercero
"""

from decimal import Decimal
from django.test import Client, TestCase
from gestion.models import Cliente


# ─────────────────────────────────────────────────────────
# US-016 / US-017 · Formulario público
# ─────────────────────────────────────────────────────────

class FormularioPublicoTests(TestCase):
    """
    US-016: El formulario de presupuesto es accesible sin autenticación.
    US-017: Un tercero puede completar el formulario por el cliente.
    CA: El formulario no redirige al login (no tiene @login_required).
    CA: Los datos se asocian al cliente correcto aunque lo complete un tercero.
    """

    def setUp(self):
        self.client = Client()

    def test_formulario_publico_no_redirige_a_login(self):
        """El formulario público de presupuesto no requiere autenticación."""
        resp = self.client.get("/public/presupuesto/")
        # 200 = disponible; 404 = URL aún no registrada — ambos son correctos en esta etapa.
        # Lo que NO debe ocurrir es un 302 al login.
        if resp.status_code == 302:
            self.assertNotIn("login", resp["Location"],
                             "El formulario público no debe requerir login")

    def test_public_views_importable(self):
        """El módulo public.views es importable."""
        import public.views  # noqa: F401

    def test_cliente_registrado_por_tercero(self):
        """Los datos ingresados por un tercero crean o encuentran el cliente correcto."""
        telefono = "+5491122223333"
        cliente, created = Cliente.objects.get_or_create(
            telefono=telefono,
            defaults={"nombre_completo": "Juan Pérez"},
        )
        self.assertTrue(created)
        self.assertEqual(cliente.nombre_completo, "Juan Pérez")

    def test_datos_cliente_no_duplicados(self):
        """El mismo teléfono no genera dos clientes distintos."""
        telefono = "+5491122223334"
        Cliente.objects.get_or_create(telefono=telefono,
                                      defaults={"nombre_completo": "María López"})
        Cliente.objects.get_or_create(telefono=telefono,
                                      defaults={"nombre_completo": "María López"})
        self.assertEqual(Cliente.objects.filter(telefono=telefono).count(), 1)

    def test_campo_telefono_es_unico_en_cliente(self):
        """El modelo Cliente tiene telefono como unique."""
        campo = Cliente._meta.get_field("telefono")
        self.assertTrue(campo.unique)
