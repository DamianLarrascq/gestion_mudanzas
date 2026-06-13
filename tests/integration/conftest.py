"""
Fixtures y factories compartidas — tier integration
Archivo: tests/integration/conftest.py

Centraliza helpers que antes vivían en tests/unit/test_models.py
para evitar acoplamiento entre tiers.

Fixtures disponibles
────────────────────
  staff_user       — usuario staff para endpoints con LoginRequired
  client_staff     — TestClient autenticado como staff_user
  sistema_user     — usuario is_active=False para webhooks
  tarifa_activa    — TarifaBase activa mínima (sobrescribe la del conftest raíz)

Factories disponibles (funciones, no fixtures)
──────────────────────────────────────────────
  make_cliente(**kw)         → Cliente
  make_camion(**kw)          → Camion
  make_user(username)        → User
  make_empleado(**kw)        → Empleado
  make_direccion(**kw)       → Direccion
  make_mudanza(cliente, **kw) → Mudanza
  make_tarifa(**kw)          → TarifaBase
  make_catalogo_item(**kw)   → CatalogoItem
  make_presupuesto(mudanza, tarifa, **kw) → Presupuesto
  make_notificacion(mudanza, **kw)        → Notificacion
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone


# ─────────────────────────────────────────────────────────────────────────────
# Factories — funciones puras, no fixtures
# Reutilizables desde cualquier test del tier sin necesidad de @pytest.fixture
# ─────────────────────────────────────────────────────────────────────────────

def make_cliente(**kw) -> "Cliente":
    from gestion.models import Cliente

    defaults: dict = dict(
        nombre_completo="Luis Martínez",
        dni="12345678",
        telefono="+5491122334455",
        email="lmartinez@mail.com",
    )
    defaults.update(kw)
    return Cliente.objects.create(**defaults)


def make_camion(**kw) -> "Camion":
    from gestion.models import Camion

    defaults: dict = dict(
        patente="PPJ142",
        modelo="Ford F-250",
        categoria=Camion.Categoria.N1,
        activo=True,
        capacidad_volumen_m3=Decimal("15.00"),
        capacidad_peso_kg=Decimal("3500.00"),
        anio=2020,
    )
    defaults.update(kw)
    return Camion.objects.create(**defaults)


def make_user(username: str = "conductor1") -> User:
    return User.objects.create_user(username=username, password="Pass1234!")


def make_empleado(user: User | None = None, **kw) -> "Empleado":
    from gestion.models import Empleado

    if user is None:
        user = make_user(username=kw.pop("username", "emp_test"))
    defaults: dict = dict(
        user=user,
        nombre="Roberto Rodríguez",
        dni="87654321",
        rol=Empleado.Rol.CONDUCTOR,
        nro_licencia="LC-001234",
        disponible=True,
    )
    defaults.update(kw)
    return Empleado.objects.create(**defaults)


def make_direccion(**kw) -> "Direccion":
    from gestion.models import Direccion

    defaults: dict = dict(
        calle="Av. Corrientes",
        numero="1234",
        piso="PB",
        localidad="CABA",
        provincia="Buenos Aires",
        codigo_postal="1043",
        tiene_ascensor=False,
    )
    defaults.update(kw)
    return Direccion.objects.create(**defaults)


def make_mudanza(cliente=None, camion=None, **kw) -> "Mudanza":
    from gestion.models import Mudanza

    if cliente is None:
        cliente = make_cliente(dni="11111111", telefono="+5491100000001")
    origen = make_direccion(calle="Calle A", numero="1")
    destino = make_direccion(calle="Calle B", numero="2")
    defaults: dict = dict(
        cliente=cliente,
        camion=camion,
        estado=Mudanza.Estado.BORRADOR,
        fecha_hora=timezone.now() + timedelta(days=2),
        origen=origen,
        destino=destino,
        distancia_km=Decimal("12.00"),
        necesita_ayudantes=True,
    )
    defaults.update(kw)
    return Mudanza.objects.create(**defaults)


def make_tarifa(**kw) -> "TarifaBase":
    from gestion.models import TarifaBase

    defaults: dict = dict(
        nombre="Tarifa Test Integración",
        precio_por_km=Decimal("800.00"),
        precio_ayudante=Decimal("3000.00"),
        recargo_piso=Decimal("1500.00"),
        recargo_hora_pico=Decimal("1.20"),
        recargo_fin_de_semana=Decimal("1.15"),
        permite_caba_feriados=False,
        activa=True,
        vigente_desde=date.today(),
        seguro_camion=Decimal("2000.00"),
        empleado_art=Decimal("500.00"),
        empleado_seguro_riesgo=Decimal("400.00"),
        empleado_seguro_ayudante=Decimal("300.00"),
        salario_conductor=Decimal("8000.00"),
        salario_ayudante=Decimal("5000.00"),
    )
    defaults.update(kw)
    return TarifaBase.objects.create(**defaults)


def make_catalogo_item(**kw) -> "CatalogoItem":
    from gestion.models import CatalogoItem

    defaults: dict = dict(
        nombre="Sofá 3 cuerpos",
        volumen_m3=Decimal("1.500"),
        peso_estimado_kg=Decimal("80.00"),
    )
    defaults.update(kw)
    return CatalogoItem.objects.create(**defaults)


def make_presupuesto(mudanza, tarifa, **kw) -> "Presupuesto":
    from gestion.models import Presupuesto

    defaults: dict = dict(
        mudanza=mudanza,
        tarifa=tarifa,
        costo_distancia=Decimal("9600.00"),   # 12 km × $800
        costo_peajes=Decimal("0.00"),
        costo_ayudantes=Decimal("3000.00"),
        costo_camion=Decimal("2500.00"),
        recargo_pisos=Decimal("0.00"),
        total=Decimal("15100.00"),
    )
    defaults.update(kw)
    return Presupuesto.objects.create(**defaults)


def make_notificacion(mudanza, **kw) -> "Notificacion":
    from gestion.models import Notificacion

    defaults: dict = dict(
        mudanza=mudanza,
        tipo=Notificacion.Tipo.CONFIRMACION,
        canal=Notificacion.Canal.WHATSAPP,
        destinatario="+5491122334455",
        enviada=False,
    )
    defaults.update(kw)
    return Notificacion.objects.create(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures pytest
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def staff_user(db) -> User:
    """Usuario staff para tests que requieren LoginRequiredMixin."""
    user, _ = User.objects.get_or_create(
        username="integ_staff",
        defaults={"is_staff": True, "is_superuser": True},
    )
    user.set_password("Pass1234!")
    user.is_staff = True
    user.is_superuser = True
    user.save()
    return user


@pytest.fixture
def client_staff(staff_user) -> Client:
    """TestClient autenticado como staff_user."""
    c = Client()
    c.login(username="integ_staff", password="Pass1234!")
    return c


@pytest.fixture
def sistema_user(db) -> User:
    """Usuario de sistema para webhooks (is_active=False)."""
    user, _ = User.objects.get_or_create(
        username="sistema",
        defaults={"is_active": False},
    )
    user.is_active = False
    user.save()
    return user


@pytest.fixture
def tarifa_activa(db) -> "TarifaBase":
    """
    TarifaBase activa para el tier integration.
    Sobrescribe la fixture homónima del conftest raíz.
    """
    return make_tarifa()
