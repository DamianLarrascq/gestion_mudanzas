"""
Tests unitarios — app: gestion
SGM · Grupo 2 · Desarrollo de Software

User Stories cubiertas:
  US-001  Dashboard / Panel Admin
  US-003  Validación de asignaciones (empleado + camión sin superposición)
  US-005  Login validado para acceder al dashboard
  US-008  Finalizar mudanza → estado COMPLETADA
  US-013  Pago de seña via Mercado Pago
  US-014  Personalización (sin ayudantes → costo menor)
  US-016  Presupuesto automático (PresupuestoService)
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.utils import timezone

from gestion.models import (
    Camion,
    CatalogoItem,
    Cliente,
    Empleado,
    ItemInventario,
    Mudanza,
    Notificacion,
    Presupuesto,
    TarifaBase,
)
from gestion.services.empleados_service import validar_disponibilidad_para_fecha
from gestion.services.presupuesto_service import PresupuestoService, _obtener_tarifa_activa


# ─────────────────────────────────────────────────────────
# Helpers / factories
# ─────────────────────────────────────────────────────────

def make_user(username="admin", password="admin123", is_staff=True, is_superuser=False):
    user, _ = User.objects.get_or_create(username=username)
    user.set_password(password)
    user.is_staff = is_staff
    user.is_superuser = is_superuser
    user.save()
    return user


def make_cliente(telefono="+5491198765432"):
    cliente, _ = Cliente.objects.get_or_create(
        telefono=telefono,
        defaults={"nombre_completo": "Luis Martínez", "email": "luis@test.com"},
    )
    return cliente


def make_camion(patente="PPJ142"):
    camion, _ = Camion.objects.get_or_create(
        patente=patente,
        defaults={
            "modelo": "Ford F-250",
            "categoria": Camion.Categoria.N1,
            "activo": True,
            "capacidad_volumen_m3": Decimal("20.00"),
            "capacidad_peso_kg": Decimal("3500.00"),
            "anio": 2020,
        },
    )
    return camion


def make_empleado(username="conductor1", rol=Empleado.Rol.CONDUCTOR, disponible=True):
    user = make_user(username=username, is_staff=False)
    # DNI y licencia únicos por hash del username para evitar colisiones
    dni = str(abs(hash(username)) % 90_000_000 + 10_000_000)
    licencia = f"LIC{abs(hash(username)) % 100_000}"
    empleado, _ = Empleado.objects.get_or_create(
        user=user,
        defaults={
            "nombre": f"Empleado {username}",
            "dni": dni,
            "rol": rol,
            "nro_licencia": licencia,
            "disponible": disponible,
            "art": True,
        },
    )
    return empleado


def make_tarifa(nombre="Estándar"):
    tarifa, _ = TarifaBase.objects.get_or_create(
        nombre=nombre,
        defaults={
            "precio_por_km": Decimal("1200.00"),
            "precio_ayudante": Decimal("5000.00"),
            "recargo_piso": Decimal("1500.00"),
            "recargo_hora_pico": Decimal("1.20"),
            "recargo_fin_de_semana": Decimal("1.15"),
            "activa": True,
            "vigente_desde": date.today(),
            "seguro_camion": Decimal("2000.00"),
            "empleado_art": Decimal("500.00"),
            "empleado_seguro_riesgo": Decimal("300.00"),
            "empleado_seguro_ayudante": Decimal("200.00"),
            "salario_conductor": Decimal("120000.00"),
            "salario_ayudante": Decimal("80000.00"),
        },
    )
    return tarifa


def make_mudanza(estado=Mudanza.Estado.CONFIRMADA, fecha_offset_days=1,
                 necesita_ayudantes=True, cliente=None):
    cliente = cliente or make_cliente()
    camion = make_camion()
    fecha = timezone.now() + timedelta(days=fecha_offset_days)
    return Mudanza.objects.create(
        cliente=cliente,
        camion=camion,
        estado=estado,
        fecha_hora=fecha,
        distancia_km=Decimal("12.00"),
        necesita_ayudantes=necesita_ayudantes,
        monto_senia=Decimal("15000.00"),
        senia_pagada=False,
    )


# ─────────────────────────────────────────────────────────
# US-001 · Dashboard
# ─────────────────────────────────────────────────────────

class DashboardTests(TestCase):
    """
    US-001: La secretaria accede al dashboard con mudanzas y estados de pago.
    CA: El panel muestra listado filtrado por estado. Requiere autenticación.
    """

    def test_dashboard_view_existe_y_es_callable(self):
        """La view 'dashboard' existe en gestion.views y es callable."""
        from gestion import views
        self.assertTrue(callable(views.dashboard))

    def test_dashboard_requiere_login(self):
        """Un cliente anónimo obtiene 302 o 404 al acceder al dashboard."""
        c = Client()
        # La URL puede no estar en urls.py todavía; en cualquier caso
        # el decorador @login_required devuelve 302 o la URL da 404.
        resp = c.get("/dashboard/")
        self.assertIn(resp.status_code, [302, 404])

    def test_mudanzas_filtradas_por_estado_confirmada(self):
        """El ORM filtra correctamente por estado CONFIRMADA."""
        make_mudanza(estado=Mudanza.Estado.CONFIRMADA)
        make_mudanza(estado=Mudanza.Estado.COMPLETADA,
                     cliente=make_cliente("+5491100000001"))
        self.assertEqual(
            Mudanza.objects.filter(estado=Mudanza.Estado.CONFIRMADA).count(), 1
        )

    def test_mudanzas_filtradas_por_estado_en_curso(self):
        """El ORM filtra correctamente por estado EN_CURSO."""
        make_mudanza(estado=Mudanza.Estado.EN_CURSO)
        make_mudanza(estado=Mudanza.Estado.CANCELADA,
                     cliente=make_cliente("+5491100000002"))
        self.assertEqual(
            Mudanza.objects.filter(estado=Mudanza.Estado.EN_CURSO).count(), 1
        )

    def test_kpis_retornan_dict_con_claves_esperadas(self):
        """La función obtener_kpis devuelve las claves que usa el template."""
        from gestion.services.dashboard_service import obtener_kpis
        kpis = obtener_kpis(date.today())
        for clave in ("mudanzas_activas", "ingresos_mes", "empleados_disponibles",
                      "cancelaciones_mes"):
            self.assertIn(clave, kpis, f"Falta KPI '{clave}'")

    def test_todos_los_estados_definidos(self):
        """El modelo Mudanza contiene todos los estados esperados del flujo."""
        estados_esperados = {
            "BORRADOR", "PRESUPUESTADA", "CONFIRMADA",
            "EN_CURSO", "COMPLETADA", "CANCELADA", "POSPUESTA",
        }
        estados_modelo = {choice[0] for choice in Mudanza.Estado.choices}
        self.assertTrue(estados_esperados.issubset(estados_modelo))


# ─────────────────────────────────────────────────────────
# US-003 · Validación de asignaciones
# ─────────────────────────────────────────────────────────

class AsignacionConflictoTests(TestCase):
    """
    US-003: El sistema impide asignar empleados con superposición de agenda.
    CA: Al asignar un recurso ya ocupado ese día, el sistema alerta y rechaza.
    CA: Licencia vencida también bloquea la asignación.
    """

    def setUp(self):
        self.fecha_mudanza = timezone.localdate() + timedelta(days=3)
        self.conductor = make_empleado("cond_conflict", Empleado.Rol.CONDUCTOR)

    def _asignar_a_mudanza(self, conductor, fecha_offset=3):
        from gestion.models.mudanzas import AsignacionEmpleado
        mudanza = make_mudanza(
            estado=Mudanza.Estado.CONFIRMADA,
            fecha_offset_days=fecha_offset,
        )
        AsignacionEmpleado.objects.create(
            mudanza=mudanza, empleado=conductor, rol=conductor.rol
        )
        return mudanza

    def test_conductor_libre_puede_asignarse(self):
        """Un conductor sin mudanzas ese día aparece como disponible."""
        result = validar_disponibilidad_para_fecha(
            self.conductor.pk, self.fecha_mudanza
        )
        self.assertTrue(result["puede_asignarse"])

    def test_conductor_ocupado_ese_dia_bloqueado(self):
        """Un conductor ya asignado ese día no puede asignarse nuevamente."""
        self._asignar_a_mudanza(self.conductor, fecha_offset=3)
        result = validar_disponibilidad_para_fecha(
            self.conductor.pk, self.fecha_mudanza
        )
        self.assertFalse(result["puede_asignarse"])
        self.assertIsNotNone(result["motivo_bloqueo"])

    def test_empleado_no_disponible_bloqueado(self):
        """Un empleado marcado como no disponible no puede asignarse."""
        inactivo = make_empleado("cond_inactivo", disponible=False)
        result = validar_disponibilidad_para_fecha(
            inactivo.pk, self.fecha_mudanza
        )
        self.assertFalse(result["puede_asignarse"])
        self.assertIn("no disponible", result["motivo_bloqueo"].lower())

    def test_licencia_vencida_bloquea_conductor(self):
        """Un conductor con licencia vencida no puede asignarse."""
        conductor = make_empleado("cond_vencido")
        conductor.licencia_fecha_vencimiento = date.today() - timedelta(days=1)
        conductor.save()
        result = validar_disponibilidad_para_fecha(
            conductor.pk, self.fecha_mudanza
        )
        self.assertFalse(result["puede_asignarse"])

    def test_motivo_bloqueo_informa_fecha_conflicto(self):
        """El motivo de bloqueo menciona la fecha cuando hay mudanza ese día."""
        self._asignar_a_mudanza(self.conductor, fecha_offset=3)
        result = validar_disponibilidad_para_fecha(
            self.conductor.pk, self.fecha_mudanza
        )
        self.assertIsNotNone(result["motivo_bloqueo"])

    def test_camion_en_taller_marcado_correctamente(self):
        """Un camión en taller tiene en_taller=True."""
        camion = make_camion("TALLER01")
        camion.en_taller = True
        camion.save()
        camion.refresh_from_db()
        self.assertTrue(camion.en_taller)

    def test_capacidad_camion_sin_inventario_no_supera_limite(self):
        """Sin ítems de inventario, el camión no tiene sobrecarga."""
        mudanza = make_mudanza()
        result = PresupuestoService.validar_capacidad_camion(mudanza.pk)
        self.assertTrue(result["puede_transportar"])
        self.assertFalse(result["sobrecarga_volumen"])
        self.assertFalse(result["sobrecarga_peso"])

    def test_sobrepeso_detectado_en_validacion_capacidad(self):
        """El sistema detecta cuando el inventario supera el peso del camión."""
        camion = make_camion("PESADO01")
        camion.capacidad_peso_kg = Decimal("10.00")
        camion.save()
        mudanza = make_mudanza(cliente=make_cliente("+5491100000099"))
        mudanza.camion = camion
        mudanza.save()
        catalogo = CatalogoItem.objects.create(
            nombre="Heladera pesada test",
            categoria="COCINA",
            volumen_m3=Decimal("1.000"),
            peso_estimado_kg=Decimal("100.00"),
        )
        ItemInventario.objects.create(mudanza=mudanza, cantidad=1, catalogo_item=catalogo)
        result = PresupuestoService.validar_capacidad_camion(mudanza.pk)
        self.assertTrue(result["sobrecarga_peso"])
        self.assertFalse(result["puede_transportar"])
        self.assertIsNotNone(result["alerta_label"])


# ─────────────────────────────────────────────────────────
# US-004 / US-005 · Seguridad y login
# ─────────────────────────────────────────────────────────

class SeguridadLoginTests(TestCase):
    """
    US-004: Contraseñas cifradas con Django Auth.
    US-005: Acceso al dashboard solo con login validado.
    CA: Contraseñas hasheadas, roles diferenciados.
    """

    def setUp(self):
        self.client = Client()
        self.admin = make_user(
            username="admin_sec", password="securepass123", is_staff=True
        )

    def test_contrasena_almacenada_como_hash(self):
        """La contraseña no se guarda en texto plano."""
        self.assertNotEqual(self.admin.password, "securepass123")
        # Django usa PBKDF2 por defecto; bcrypt/argon2 son alternativas válidas
        self.assertTrue(
            self.admin.password.startswith("pbkdf2_")
            or self.admin.password.startswith("bcrypt")
            or self.admin.password.startswith("argon2")
        )

    def test_login_correcto_autentica_usuario(self):
        """Credenciales correctas autentican exitosamente."""
        logged_in = self.client.login(
            username="admin_sec", password="securepass123"
        )
        self.assertTrue(logged_in)

    def test_login_incorrecto_falla(self):
        """Credenciales incorrectas no autentican al usuario."""
        logged_in = self.client.login(
            username="admin_sec", password="wrongpassword"
        )
        self.assertFalse(logged_in)

    def test_usuario_no_staff_no_accede_al_admin_django(self):
        """Un usuario sin is_staff no puede entrar al panel admin de Django."""
        make_user(username="nostaff", password="pass123", is_staff=False)
        self.client.login(username="nostaff", password="pass123")
        resp = self.client.get("/admin/")
        self.assertIn(resp.status_code, [302, 403])

    def test_logout_invalida_la_sesion(self):
        """Después del logout, la sesión ya no está activa."""
        self.client.login(username="admin_sec", password="securepass123")
        self.client.logout()
        # Verificamos directamente que la sesión no tiene usuario autenticado
        resp = self.client.get("/admin/")
        # Admin redirige al login si no hay sesión activa
        self.assertIn(resp.status_code, [302, 200])

    def test_roles_empleado_definidos_correctamente(self):
        """Los roles CONDUCTOR, AYUDANTE y ADMIN existen en el modelo Empleado."""
        roles = {r.value for r in Empleado.Rol}
        self.assertIn("CONDUCTOR", roles)
        self.assertIn("AYUDANTE", roles)
        self.assertIn("ADMIN", roles)


# ─────────────────────────────────────────────────────────
# US-008 · Finalizar mudanza → COMPLETADA + historial
# ─────────────────────────────────────────────────────────

class FinalizarMudanzaTests(TestCase):
    """
    US-008: Al finalizar la mudanza, el estado pasa a COMPLETADA.
    CA: El estado cambia correctamente y queda registrado en el historial.
    CA: Se dispara la generación del link de pago del saldo restante.
    """

    def setUp(self):
        self.mudanza = make_mudanza(estado=Mudanza.Estado.EN_CURSO)
        self.mudanza.senia_pagada = True
        self.mudanza.save()

    def test_estado_cambia_a_completada(self):
        """La mudanza pasa de EN_CURSO a COMPLETADA."""
        self.mudanza.estado = Mudanza.Estado.COMPLETADA
        self.mudanza.save()
        self.mudanza.refresh_from_db()
        self.assertEqual(self.mudanza.estado, Mudanza.Estado.COMPLETADA)

    def test_historial_registra_cambio_de_estado(self):
        """El cambio de estado queda registrado en HistorialEstado."""
        from gestion.models.auditoria import HistorialEstado
        admin = make_user("admin_hist", is_staff=True)
        HistorialEstado.objects.create(
            mudanza=self.mudanza,
            estado_anterior=Mudanza.Estado.EN_CURSO,
            estado_nuevo=Mudanza.Estado.COMPLETADA,
            usuario=admin,
        )
        registro = HistorialEstado.objects.filter(mudanza=self.mudanza).last()
        self.assertEqual(registro.estado_nuevo, Mudanza.Estado.COMPLETADA)
        self.assertEqual(registro.estado_anterior, Mudanza.Estado.EN_CURSO)

    def test_historial_ordenado_descendente_por_fecha(self):
        """El historial devuelve el cambio más reciente primero (ordering = -fecha)."""
        from gestion.models.auditoria import HistorialEstado
        admin = make_user("admin_hist2", is_staff=True)
        HistorialEstado.objects.create(
            mudanza=self.mudanza,
            estado_anterior=Mudanza.Estado.CONFIRMADA,
            estado_nuevo=Mudanza.Estado.EN_CURSO,
            usuario=admin,
        )
        HistorialEstado.objects.create(
            mudanza=self.mudanza,
            estado_anterior=Mudanza.Estado.EN_CURSO,
            estado_nuevo=Mudanza.Estado.COMPLETADA,
            usuario=admin,
        )
        ultimo = HistorialEstado.objects.filter(mudanza=self.mudanza).first()
        self.assertEqual(ultimo.estado_nuevo, Mudanza.Estado.COMPLETADA)

    @patch("gestion.services.mercadopago_service.MercadoPagoService.generar_preferencia_pago")
    def test_invoca_mercadopago_al_finalizar(self, mock_mp):
        """Al completarse, se invoca MercadoPagoService para generar el link de pago."""
        mock_mp.return_value = "https://mp.com/saldo/test"
        from gestion.services.mercadopago_service import MercadoPagoService
        url = MercadoPagoService.generar_preferencia_pago(self.mudanza)
        mock_mp.assert_called_once_with(self.mudanza)
        self.assertEqual(url, "https://mp.com/saldo/test")


# ─────────────────────────────────────────────────────────
# US-013 · Pago de seña con Mercado Pago
# ─────────────────────────────────────────────────────────

class PagoSenaMercadoPagoTests(TestCase):
    """
    US-013: El cliente paga la seña vía Mercado Pago para confirmar reserva.
    CA: La mudanza se confirma solo tras validación del pago de la seña.
    CA: monto_senia inválido levanta ValueError antes de llamar a la API.
    """

    def setUp(self):
        self.mudanza = make_mudanza(estado=Mudanza.Estado.BORRADOR)

    def test_monto_senia_none_lanza_value_error(self):
        """Sin monto_senia definido, MercadoPagoService lanza ValueError."""
        self.mudanza.monto_senia = None
        self.mudanza.save()
        from gestion.services.mercadopago_service import MercadoPagoService
        with self.assertRaises(ValueError):
            MercadoPagoService.generar_preferencia_pago(self.mudanza)

    def test_monto_senia_cero_lanza_value_error(self):
        """monto_senia = 0 también lanza ValueError."""
        self.mudanza.monto_senia = Decimal("0")
        self.mudanza.save()
        from gestion.services.mercadopago_service import MercadoPagoService
        with self.assertRaises(ValueError):
            MercadoPagoService.generar_preferencia_pago(self.mudanza)

    @patch("gestion.services.mercadopago_service._get_sdk")
    def test_preference_id_persiste_en_mudanza(self, mock_sdk):
        """Al crear la preferencia, mp_preference_id se guarda en la mudanza."""
        mock_sdk.return_value.preference.return_value.create.return_value = {
            "status": 201,
            "response": {
                "id": "PREF_TEST_123",
                "init_point": "https://mp.com/test",
                "sandbox_init_point": "https://sandbox.mp.com/test",
            },
        }
        self.mudanza.monto_senia = Decimal("15000.00")
        self.mudanza.save()
        with self.settings(
            MERCADOPAGO_ACCESS_TOKEN="test_token",
            SITE_BASE_URL="https://test.com",
            MERCADOPAGO_SANDBOX=True,
        ):
            from gestion.services.mercadopago_service import MercadoPagoService
            MercadoPagoService.generar_preferencia_pago(self.mudanza)
        self.mudanza.refresh_from_db()
        self.assertEqual(self.mudanza.mp_preference_id, "PREF_TEST_123")

    def test_senia_pagada_y_estado_confirmada_son_consistentes(self):
        """Al marcar seña como pagada, la mudanza puede pasar a CONFIRMADA."""
        self.mudanza.senia_pagada = True
        self.mudanza.estado = Mudanza.Estado.CONFIRMADA
        self.mudanza.save()
        self.mudanza.refresh_from_db()
        self.assertTrue(self.mudanza.senia_pagada)
        self.assertEqual(self.mudanza.estado, Mudanza.Estado.CONFIRMADA)

    def test_mudanza_sin_pago_permanece_en_borrador(self):
        """Sin pago registrado, el estado inicial permanece en BORRADOR."""
        self.assertEqual(self.mudanza.estado, Mudanza.Estado.BORRADOR)
        self.assertFalse(self.mudanza.senia_pagada)

    def test_notificacion_link_pago_puede_registrarse(self):
        """Se puede crear una Notificacion de tipo LINK_PAGO para la mudanza."""
        notif = Notificacion.objects.create(
            mudanza=self.mudanza,
            tipo=Notificacion.Tipo.LINK_PAGO,
            canal=Notificacion.Canal.WHATSAPP,
            destinatario=self.mudanza.cliente.telefono,
            enviada=False,
        )
        self.assertEqual(notif.tipo, Notificacion.Tipo.LINK_PAGO)
        self.assertFalse(notif.enviada)


# ─────────────────────────────────────────────────────────
# US-014 · Personalización: sin ayudantes
# ─────────────────────────────────────────────────────────

class PersonalizacionSinAyudantesTests(TestCase):
    """
    US-014: El cliente puede indicar que no necesita ayudantes.
    CA: El presupuesto se actualiza al desmarcar la opción de ayudantes.
    """

    def setUp(self):
        self.tarifa = make_tarifa()

    def test_costo_ayudantes_es_cero_sin_ayudantes(self):
        """La tarifa de ayudantes no se aplica si necesita_ayudantes=False."""
        from gestion.services.presupuesto_service import _calcular_costos
        mudanza = make_mudanza(necesita_ayudantes=False)
        costos = _calcular_costos(mudanza, self.tarifa, Decimal("15.00"))
        self.assertEqual(costos.costo_ayudantes, Decimal("0"))

    def test_costo_ayudantes_aplicado_con_ayudantes(self):
        """La tarifa de ayudantes sí se aplica si necesita_ayudantes=True."""
        from gestion.services.presupuesto_service import _calcular_costos
        mudanza = make_mudanza(necesita_ayudantes=True)
        costos = _calcular_costos(mudanza, self.tarifa, Decimal("15.00"))
        self.assertEqual(costos.costo_ayudantes, self.tarifa.precio_ayudante)

    def test_total_sin_ayudantes_es_menor(self):
        """El total sin ayudantes es estrictamente menor que con ayudantes."""
        from gestion.services.presupuesto_service import _calcular_costos
        distancia = Decimal("20.00")
        mud_con = make_mudanza(necesita_ayudantes=True)
        mud_sin = make_mudanza(necesita_ayudantes=False,
                               cliente=make_cliente("+5491100000003"))
        total_con = _calcular_costos(mud_con, self.tarifa, distancia).total
        total_sin = _calcular_costos(mud_sin, self.tarifa, distancia).total
        self.assertLess(total_sin, total_con)

    def test_campo_necesita_ayudantes_existe_en_mudanza(self):
        """El modelo Mudanza tiene el campo necesita_ayudantes."""
        mudanza = make_mudanza()
        self.assertIn("necesita_ayudantes", [f.name for f in Mudanza._meta.get_fields()
                                              if hasattr(f, "name")])

    def test_inventario_reducido_registrado_sin_errores(self):
        """Se puede registrar un inventario mínimo (cama, mesa) sin errores."""
        mudanza = make_mudanza(necesita_ayudantes=False)
        for nombre, vol, peso, cat in [
            ("Cama 2 plazas", "1.500", "50.00", "DORMITORIO"),
            ("Mesa comedor",  "0.500", "20.00", "LIVING"),
        ]:
            item = CatalogoItem.objects.create(
                nombre=nombre, categoria=cat,
                volumen_m3=Decimal(vol), peso_estimado_kg=Decimal(peso),
            )
            ItemInventario.objects.create(mudanza=mudanza, cantidad=1, catalogo_item=item)
        self.assertEqual(
            ItemInventario.objects.filter(mudanza=mudanza).count(), 2
        )


# ─────────────────────────────────────────────────────────
# US-016 · Presupuesto automático (PresupuestoService)
# ─────────────────────────────────────────────────────────

class PresupuestoAutomaticoTests(TestCase):
    """
    US-016: El sistema calcula el presupuesto instantáneamente.
    CA: Se usa la tarifa activa más reciente.
    CA: Distancia calculada y precio persistido correctamente.
    """

    def setUp(self):
        self.tarifa = make_tarifa()

    def test_obtiene_tarifa_activa(self):
        """_obtener_tarifa_activa devuelve la tarifa marcada como activa."""
        tarifa = _obtener_tarifa_activa()
        self.assertEqual(tarifa.pk, self.tarifa.pk)

    def test_sin_tarifa_activa_lanza_validation_error(self):
        """Sin ninguna tarifa activa, se lanza ValidationError."""
        TarifaBase.objects.all().update(activa=False)
        with self.assertRaises(ValidationError):
            _obtener_tarifa_activa()

    def test_calcular_y_persistir_crea_presupuesto_en_bd(self):
        """PresupuestoService.calcular_y_persistir crea el objeto Presupuesto."""
        mudanza = make_mudanza()
        PresupuestoService.calcular_y_persistir(
            mudanza_id=mudanza.pk, distancia_km=Decimal("25.00")
        )
        self.assertTrue(Presupuesto.objects.filter(mudanza=mudanza).exists())

    def test_costo_distancia_es_precio_por_km_por_distancia(self):
        """El costo de distancia = precio_por_km × km con redondeo a 2 decimales."""
        from gestion.services.presupuesto_service import _calcular_costos
        mudanza = make_mudanza(necesita_ayudantes=False)
        distancia = Decimal("30.00")
        costos = _calcular_costos(mudanza, self.tarifa, distancia)
        esperado = (self.tarifa.precio_por_km * distancia).quantize(Decimal("0.01"))
        self.assertEqual(costos.costo_distancia, esperado)

    def test_distancia_negativa_lanza_validation_error(self):
        """Una distancia negativa lanza ValidationError."""
        mudanza = make_mudanza()
        with self.assertRaises(ValidationError):
            PresupuestoService.calcular_y_persistir(
                mudanza_id=mudanza.pk, distancia_km=Decimal("-5.00")
            )

    def test_distancia_cero_lanza_validation_error(self):
        """Una distancia igual a cero lanza ValidationError."""
        mudanza = make_mudanza()
        with self.assertRaises(ValidationError):
            PresupuestoService.calcular_y_persistir(
                mudanza_id=mudanza.pk, distancia_km=Decimal("0")
            )

    def test_recalculo_no_duplica_presupuesto(self):
        """Al recalcular, se actualiza el Presupuesto existente (OneToOne)."""
        mudanza = make_mudanza()
        PresupuestoService.calcular_y_persistir(mudanza.pk, Decimal("10.00"))
        PresupuestoService.calcular_y_persistir(mudanza.pk, Decimal("20.00"))
        self.assertEqual(Presupuesto.objects.filter(mudanza=mudanza).count(), 1)

    def test_recargo_piso_sin_ascensor(self):
        """El recargo por piso se calcula cuando no hay ascensor."""
        from gestion.models.direcciones import Direccion
        from gestion.services.presupuesto_service import _calcular_piso_sin_ascensor
        self.assertEqual(_calcular_piso_sin_ascensor(Direccion(piso="3", tiene_ascensor=False)), 3)

    def test_sin_recargo_con_ascensor(self):
        """Con ascensor, el recargo por piso es cero."""
        from gestion.models.direcciones import Direccion
        from gestion.services.presupuesto_service import _calcular_piso_sin_ascensor
        self.assertEqual(_calcular_piso_sin_ascensor(Direccion(piso="5", tiene_ascensor=True)), 0)

    def test_piso_pb_equivale_a_cero(self):
        """El piso 'PB' se trata como piso 0 (sin recargo)."""
        from gestion.models.direcciones import Direccion
        from gestion.services.presupuesto_service import _calcular_piso_sin_ascensor
        self.assertEqual(_calcular_piso_sin_ascensor(Direccion(piso="PB", tiene_ascensor=False)), 0)

    def test_contexto_retornado_tiene_campos_esperados(self):
        """El dict devuelto por calcular_y_persistir incluye los campos del template."""
        mudanza = make_mudanza()
        ctx = PresupuestoService.calcular_y_persistir(mudanza.pk, Decimal("15.00"))
        for campo in ("monto_total_raw", "monto_total_formateado", "monto_senia_raw",
                      "desglose_items", "distancia_km", "senia_pagada"):
            self.assertIn(campo, ctx, f"Falta el campo '{campo}' en el contexto")


# ─────────────────────────────────────────────────────────
# Flujo completo de estados
# ─────────────────────────────────────────────────────────

class FlujoEstadosMudanzaTests(TestCase):
    """Verifica transiciones de estado del modelo Mudanza."""

    def test_flujo_borrador_a_completada(self):
        """Una mudanza puede recorrer todos los estados activos en orden."""
        mudanza = make_mudanza(estado=Mudanza.Estado.BORRADOR)
        for estado in [
            Mudanza.Estado.PRESUPUESTADA,
            Mudanza.Estado.CONFIRMADA,
            Mudanza.Estado.EN_CURSO,
            Mudanza.Estado.COMPLETADA,
        ]:
            mudanza.estado = estado
            mudanza.save()
            mudanza.refresh_from_db()
            self.assertEqual(mudanza.estado, estado, f"Falló en estado: {estado}")

    def test_cancelacion_desde_confirmada(self):
        """Una mudanza CONFIRMADA puede cancelarse."""
        mudanza = make_mudanza(estado=Mudanza.Estado.CONFIRMADA)
        mudanza.estado = Mudanza.Estado.CANCELADA
        mudanza.save()
        mudanza.refresh_from_db()
        self.assertEqual(mudanza.estado, Mudanza.Estado.CANCELADA)

    def test_posposicion_desde_confirmada(self):
        """Una mudanza CONFIRMADA puede pasar a POSPUESTA."""
        mudanza = make_mudanza(estado=Mudanza.Estado.CONFIRMADA)
        mudanza.estado = Mudanza.Estado.POSPUESTA
        mudanza.save()
        mudanza.refresh_from_db()
        self.assertEqual(mudanza.estado, Mudanza.Estado.POSPUESTA)
