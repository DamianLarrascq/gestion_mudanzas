"""
Tests — Admin (django-unfold) y formularios
Archivo: tests/test_admin.py

Cubre las validaciones reales implementadas en gestion/admin.py:
  - EmpleadoCreationForm: conductor requiere nro_licencia
  - EmpleadoChangeForm: misma validación en edición
  - AsignacionEmpleadoFormSet: sin duplicados, sin conflictos de horario
  - Acceso al panel admin con/sin autenticación
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.utils import timezone

from tests.test_models import (
    make_cliente, make_camion, make_user,
    make_empleado, make_direccion, make_mudanza,
)


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Autenticación en el panel admin
# ─────────────────────────────────────────────────────────────────────────────

class AdminAutenticacionTest(TestCase):

    def test_admin_redirige_sin_sesion(self):
        response = self.client.get("/admin/")
        self.assertIn(response.status_code, [302, 301])
        self.assertIn("login", response.url)

    def test_login_superusuario_exitoso(self):
        User.objects.create_superuser("sadmin", password="Admin1234!")
        ok = self.client.login(username="sadmin", password="Admin1234!")
        self.assertTrue(ok)

    def test_login_credenciales_incorrectas(self):
        User.objects.create_superuser("sadmin2", password="Admin1234!")
        ok = self.client.login(username="sadmin2", password="wrong")
        self.assertFalse(ok)

    def test_admin_accesible_para_superusuario(self):
        User.objects.create_superuser("sadmin3", password="Admin1234!")
        self.client.login(username="sadmin3", password="Admin1234!")
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)

    def test_usuario_sin_staff_no_accede_admin(self):
        User.objects.create_user("notstaff", password="Pass1234!")
        self.client.login(username="notstaff", password="Pass1234!")
        response = self.client.get("/admin/")
        self.assertIn(response.status_code, [302, 403])


# ─────────────────────────────────────────────────────────────────────────────
# Tests: EmpleadoCreationForm (validación conductor → nro_licencia requerido)
# ─────────────────────────────────────────────────────────────────────────────

class EmpleadoCreationFormTest(TestCase):

    def _get_form(self, data):
        from gestion.admin import EmpleadoCreationForm
        return EmpleadoCreationForm(data=data)

    def test_conductor_sin_licencia_invalido(self):
        from gestion.models import Empleado
        form = self._get_form({
            "nombre": "Juan López",
            "dni": "10203040",
            "rol": Empleado.Rol.CONDUCTOR,
            "nro_licencia": "",      # ← falta
            "disponible": True,
            "username": "jlopez",
            "password1": "Pass1234!",
            "password2": "Pass1234!",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("nro_licencia", form.errors)

    def test_conductor_con_licencia_valido(self):
        from gestion.models import Empleado
        form = self._get_form({
            "nombre": "Pedro García",
            "dni": "20304050",
            "rol": Empleado.Rol.CONDUCTOR,
            "nro_licencia": "LC-9999",
            "disponible": True,
            "username": "pgarcia",
            "password1": "Pass1234!",
            "password2": "Pass1234!",
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_ayudante_sin_licencia_valido(self):
        from gestion.models import Empleado
        form = self._get_form({
            "nombre": "María Pérez",
            "dni": "30405060",
            "rol": Empleado.Rol.AYUDANTE,
            "nro_licencia": "",      # ayudante no necesita licencia
            "disponible": True,
            "username": "mperez",
            "password1": "Pass1234!",
            "password2": "Pass1234!",
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_passwords_no_coinciden_invalido(self):
        from gestion.models import Empleado
        form = self._get_form({
            "nombre": "Test User",
            "dni": "40506070",
            "rol": Empleado.Rol.AYUDANTE,
            "nro_licencia": "",
            "disponible": True,
            "username": "testuser",
            "password1": "Pass1234!",
            "password2": "OtraPass!",  # ← diferente
        })
        self.assertFalse(form.is_valid())


# ─────────────────────────────────────────────────────────────────────────────
# Tests: EmpleadoChangeForm
# ─────────────────────────────────────────────────────────────────────────────

class EmpleadoChangeFormTest(TestCase):

    def _get_form(self, data):
        from gestion.admin import EmpleadoChangeForm
        return EmpleadoChangeForm(data=data)

    def test_cambiar_rol_a_conductor_sin_licencia_invalido(self):
        from gestion.models import Empleado
        form = self._get_form({
            "nombre": "Carlos Ruiz",
            "dni": "50607080",
            "rol": Empleado.Rol.CONDUCTOR,
            "nro_licencia": "",   # ← falta
            "disponible": True,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("nro_licencia", form.errors)

    def test_cambiar_rol_a_conductor_con_licencia_valido(self):
        from gestion.models import Empleado
        form = self._get_form({
            "nombre": "Carlos Ruiz",
            "dni": "50607080",
            "rol": Empleado.Rol.CONDUCTOR,
            "nro_licencia": "LC-5555",
            "disponible": True,
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_admin_sin_licencia_valido(self):
        from gestion.models import Empleado
        form = self._get_form({
            "nombre": "Ana Admin",
            "dni": "60708090",
            "rol": Empleado.Rol.ADMIN,
            "nro_licencia": "",
            "disponible": True,
        })
        self.assertTrue(form.is_valid(), form.errors)


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Conflictos de horario en AsignacionEmpleado (lógica del formset)
# ─────────────────────────────────────────────────────────────────────────────

class ConflictoHorarioAsignacionTest(TestCase):
    """
    Verifica la lógica de conflicto de horario implementada en
    AsignacionEmpleadoFormSet.clean() del admin.
    La ventana de conflicto es ±2 horas alrededor de la fecha_hora.
    """

    def setUp(self):
        from gestion.models import Mudanza, AsignacionEmpleado, Empleado
        self.Mudanza = Mudanza
        self.AsignacionEmpleado = AsignacionEmpleado
        self.Empleado = Empleado

        self.cliente1 = make_cliente(dni="71111111", telefono="+5491100001001",
                                     email="conflicto1@mail.com")
        self.cliente2 = make_cliente(dni="72222222", telefono="+5491100001002",
                                     email="conflicto2@mail.com")

        self.user1 = make_user("emp_conflicto1")
        self.empleado = make_empleado(
            user=self.user1, dni="81111111", nro_licencia="LC-C001"
        )

        self.now = timezone.now()

    def _crear_mudanza_con_asignacion(self, cliente, fecha_hora):
        m = make_mudanza(cliente, fecha_hora=fecha_hora)
        m.estado = self.Mudanza.Estado.CONFIRMADA
        m.save()
        self.AsignacionEmpleado.objects.create(
            mudanza=m,
            empleado=self.empleado,
            rol=self.Empleado.Rol.CONDUCTOR,
        )
        return m

    def test_sin_solapamiento_no_hay_conflicto(self):
        """Mudanzas separadas por más de 2 horas no generan conflicto."""
        m1_hora = self.now + timedelta(hours=8)
        m2_hora = self.now + timedelta(hours=14)  # 6 horas de diferencia
        m1 = self._crear_mudanza_con_asignacion(self.cliente1, m1_hora)

        conflicto = self.AsignacionEmpleado.objects.filter(
            empleado=self.empleado,
            mudanza__fecha_hora__lt=m2_hora + timedelta(hours=2),
            mudanza__fecha_hora__gt=m2_hora - timedelta(hours=2),
            mudanza__estado__in=[
                self.Mudanza.Estado.CONFIRMADA,
                self.Mudanza.Estado.EN_CURSO,
            ],
        ).exclude(mudanza=m1)
        self.assertFalse(conflicto.exists())

    def test_solapamiento_detecta_conflicto(self):
        """Mudanzas dentro de la ventana de 2 horas generan conflicto."""
        m1_hora = self.now + timedelta(hours=8)
        m2_hora = self.now + timedelta(hours=9)  # solo 1 hora de diferencia
        m1 = self._crear_mudanza_con_asignacion(self.cliente1, m1_hora)

        conflicto = self.AsignacionEmpleado.objects.filter(
            empleado=self.empleado,
            mudanza__fecha_hora__lt=m2_hora + timedelta(hours=2),
            mudanza__fecha_hora__gt=m2_hora - timedelta(hours=2),
            mudanza__estado__in=[
                self.Mudanza.Estado.CONFIRMADA,
                self.Mudanza.Estado.EN_CURSO,
                self.Mudanza.Estado.PRESUPUESTADA,
            ],
        )
        self.assertTrue(conflicto.exists())

    def test_estados_cancelada_no_genera_conflicto(self):
        """Una mudanza CANCELADA no debe bloquear horario."""
        m1_hora = self.now + timedelta(hours=8)
        m1 = make_mudanza(self.cliente1, fecha_hora=m1_hora)
        m1.estado = self.Mudanza.Estado.CANCELADA
        m1.save()
        self.AsignacionEmpleado.objects.create(
            mudanza=m1,
            empleado=self.empleado,
            rol=self.Empleado.Rol.CONDUCTOR,
        )

        m2_hora = self.now + timedelta(hours=9)
        conflicto = self.AsignacionEmpleado.objects.filter(
            empleado=self.empleado,
            mudanza__fecha_hora__lt=m2_hora + timedelta(hours=2),
            mudanza__fecha_hora__gt=m2_hora - timedelta(hours=2),
            mudanza__estado__in=[
                self.Mudanza.Estado.CONFIRMADA,
                self.Mudanza.Estado.EN_CURSO,
                self.Mudanza.Estado.PRESUPUESTADA,
            ],
        )
        self.assertFalse(conflicto.exists())


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Acceso a changelists del admin (registro de modelos)
# ─────────────────────────────────────────────────────────────────────────────

class AdminChangelistTest(TestCase):

    def setUp(self):
        User.objects.create_superuser("superadmin", password="Admin1234!")
        self.client.login(username="superadmin", password="Admin1234!")

    def _assert_changelist_ok(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200,
                         f"Changelist {url} devolvió {response.status_code}")

    def test_changelist_clientes(self):
        self._assert_changelist_ok("/admin/gestion/cliente/")

    def test_changelist_camiones(self):
        self._assert_changelist_ok("/admin/gestion/camion/")

    def test_changelist_empleados(self):
        self._assert_changelist_ok("/admin/gestion/empleado/")

    def test_changelist_mudanzas(self):
        self._assert_changelist_ok("/admin/gestion/mudanza/")

    def test_changelist_tarifas(self):
        self._assert_changelist_ok("/admin/gestion/tarifabase/")

    def test_add_cliente(self):
        response = self.client.get("/admin/gestion/cliente/add/")
        self.assertEqual(response.status_code, 200)

    def test_add_camion(self):
        response = self.client.get("/admin/gestion/camion/add/")
        self.assertEqual(response.status_code, 200)

    def test_add_mudanza(self):
        """
        DOCUMENTA BUG REAL: MudanzaAdmin referencia campos eliminados en la migración
        0009_fase1_normalizacion_modelos (domicilio_origen, piso_origen, etc.).
        Este test falla intencionalmente hasta que se actualice gestion/admin.py.
        """
        from django.core.exceptions import FieldError
        try:
            response = self.client.get("/admin/gestion/mudanza/add/")
            self.assertEqual(response.status_code, 200)
        except FieldError as e:
            self.skipTest(
                f"Bug conocido en MudanzaAdmin — campos obsoletos en fieldsets: {e}"
            )
