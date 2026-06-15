"""
Factories de prueba — SGM · Grupo 2
Archivo: tests/factories.py

Todas las factories usan valores ESTÁTICOS Y FIJOS para garantizar
consistencia entre runs. Los campos únicos (DNI, patente, email, etc.)
son diferenciados por el sufijo numérico del nombre de la factory:
  ClienteFactory          → cliente base
  ClienteFactory2..5      → clientes adicionales (total 5)
  ClienteRepetidoFactory  → cliente "duplicado intencional" (mismo nombre que
                            ClienteFactory, distintos campos únicos)

Dependencias:
  factory-boy==3.3.3   (ver requirements.txt)
  Django auth.User     (built-in)
  gestion.models.*

Convención de uso:
  from tests.factories import ClienteFactory, CamionFactory, EmpleadoFactory

  def test_algo(db):
      cliente = ClienteFactory()
      camion  = CamionFactory()

IMPORTANTE: Estas factories NO reemplazan ni modifican los helpers
make_* existentes en tests/integration/conftest.py ni en gestion/tests.py.
Conviven en paralelo como alternativa declarativa.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import factory
from django.contrib.auth.models import User
from factory.django import DjangoModelFactory


# ─────────────────────────────────────────────────────────────────────────────
# User (Django Auth)
# ─────────────────────────────────────────────────────────────────────────────

class UserFactory(DjangoModelFactory):
    """
    Usuario base: activo, sin privilegios especiales.
    Utilizado como dependencia de EmpleadoFactory.
    """

    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = "empleado_factory_01"
    first_name = "Roberto"
    last_name = "Rodríguez"
    email = "rrodriguez.factory@sgm.test"
    is_staff = False
    is_superuser = False
    is_active = True
    password = factory.PostGenerationMethodCall("set_password", "TestPass1234!")


class UserFactory2(DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = "empleado_factory_02"
    first_name = "Marcos"
    last_name = "López"
    email = "mlopez.factory@sgm.test"
    is_staff = False
    is_active = True
    password = factory.PostGenerationMethodCall("set_password", "TestPass1234!")


class UserFactory3(DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = "empleado_factory_03"
    first_name = "Germán"
    last_name = "Fernández"
    email = "gfernandez.factory@sgm.test"
    is_staff = False
    is_active = True
    password = factory.PostGenerationMethodCall("set_password", "TestPass1234!")


class UserFactory4(DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = "empleado_factory_04"
    first_name = "Karina"
    last_name = "Vega"
    email = "kvega.factory@sgm.test"
    is_staff = False
    is_active = True
    password = factory.PostGenerationMethodCall("set_password", "TestPass1234!")


# ─────────────────────────────────────────────────────────────────────────────
# Cliente (5 únicos + 1 repetido)
# El "cliente repetido" comparte nombre_completo con ClienteFactory pero
# tiene DNI, teléfono y email distintos → no viola constraints UNIQUE.
# ─────────────────────────────────────────────────────────────────────────────

class ClienteFactory(DjangoModelFactory):
    """Cliente #1 — base de referencia."""

    class Meta:
        model = "gestion.Cliente"
        django_get_or_create = ("dni",)

    nombre_completo = "Luis Martínez"
    dni = "20111111"
    telefono = "+5491122334401"
    email = "lmartinez.factory01@sgm.test"
    fecha_nacimiento = date(1985, 3, 15)


class ClienteFactory2(DjangoModelFactory):
    """Cliente #2."""

    class Meta:
        model = "gestion.Cliente"
        django_get_or_create = ("dni",)

    nombre_completo = "Sara Gómez"
    dni = "20222222"
    telefono = "+5491122334402"
    email = "sgomez.factory02@sgm.test"
    fecha_nacimiento = date(1990, 7, 22)


class ClienteFactory3(DjangoModelFactory):
    """Cliente #3."""

    class Meta:
        model = "gestion.Cliente"
        django_get_or_create = ("dni",)

    nombre_completo = "Pablo Torres"
    dni = "20333333"
    telefono = "+5491122334403"
    email = "ptorres.factory03@sgm.test"
    fecha_nacimiento = date(1978, 11, 5)


class ClienteFactory4(DjangoModelFactory):
    """Cliente #4."""

    class Meta:
        model = "gestion.Cliente"
        django_get_or_create = ("dni",)

    nombre_completo = "María Díaz"
    dni = "20444444"
    telefono = "+5491122334404"
    email = "mdiaz.factory04@sgm.test"
    fecha_nacimiento = date(1995, 1, 30)


class ClienteFactory5(DjangoModelFactory):
    """Cliente #5."""

    class Meta:
        model = "gestion.Cliente"
        django_get_or_create = ("dni",)

    nombre_completo = "Jorge Ruiz"
    dni = "20555555"
    telefono = "+5491122334405"
    email = "jruiz.factory05@sgm.test"
    fecha_nacimiento = date(1982, 9, 14)


class ClienteRepetidoFactory(DjangoModelFactory):
    """
    Cliente "repetido" — mismo nombre_completo que ClienteFactory (#1)
    para simular el escenario de clientes homónimos en la base de datos.
    DNI, teléfono y email son distintos para respetar los constraints UNIQUE.
    """

    class Meta:
        model = "gestion.Cliente"
        django_get_or_create = ("dni",)

    nombre_completo = "Luis Martínez"   # mismo nombre que ClienteFactory
    dni = "20111199"                     # DNI diferente → no hay clash
    telefono = "+5491122334499"
    email = "lmartinez.dup.factory@sgm.test"
    fecha_nacimiento = date(1985, 3, 15)


# ─────────────────────────────────────────────────────────────────────────────
# Camion (6 vehículos)
# Patentes prefijadas con "FCT" para no colisionar con las de los tests
# existentes (PPJ142, TALLER01, PESADO01, TALL02, etc.)
# ─────────────────────────────────────────────────────────────────────────────

class CamionFactory(DjangoModelFactory):
    """Camión #1 — Ford F-250, categoría N1."""

    class Meta:
        model = "gestion.Camion"
        django_get_or_create = ("patente",)

    patente = "FCT001"
    modelo = "Ford F-250"
    categoria = "N1"
    activo = True
    capacidad_volumen_m3 = Decimal("20.00")
    capacidad_peso_kg = Decimal("3500.00")
    anio = 2020
    en_taller = False
    vtv_fecha_vencimiento = date(2026, 6, 30)
    seguro_fecha_vencimiento = date(2026, 8, 15)
    patente_fecha_vencimiento = date(2027, 1, 10)


class CamionFactory2(DjangoModelFactory):
    """Camión #2 — Mercedes Sprinter, categoría N1."""

    class Meta:
        model = "gestion.Camion"
        django_get_or_create = ("patente",)

    patente = "FCT002"
    modelo = "Mercedes Sprinter"
    categoria = "N1"
    activo = True
    capacidad_volumen_m3 = Decimal("18.00")
    capacidad_peso_kg = Decimal("3200.00")
    anio = 2019
    en_taller = False


class CamionFactory3(DjangoModelFactory):
    """Camión #3 — Iveco Daily, categoría N1."""

    class Meta:
        model = "gestion.Camion"
        django_get_or_create = ("patente",)

    patente = "FCT003"
    modelo = "Iveco Daily"
    categoria = "N1"
    activo = True
    capacidad_volumen_m3 = Decimal("15.00")
    capacidad_peso_kg = Decimal("2800.00")
    anio = 2021
    en_taller = False


class CamionFactory4(DjangoModelFactory):
    """Camión #4 — Volkswagen 9.160, categoría N2."""

    class Meta:
        model = "gestion.Camion"
        django_get_or_create = ("patente",)

    patente = "FCT004"
    modelo = "Volkswagen 9.160"
    categoria = "N2"
    activo = True
    capacidad_volumen_m3 = Decimal("30.00")
    capacidad_peso_kg = Decimal("5500.00")
    anio = 2018
    en_taller = False


class CamionFactory5(DjangoModelFactory):
    """Camión #5 — Renault Master, categoría N1, en taller."""

    class Meta:
        model = "gestion.Camion"
        django_get_or_create = ("patente",)

    patente = "FCT005"
    modelo = "Renault Master"
    categoria = "N1"
    activo = True
    capacidad_volumen_m3 = Decimal("14.00")
    capacidad_peso_kg = Decimal("2500.00")
    anio = 2017
    en_taller = True     # fuera de servicio → útil para tests de flota


class CamionFactory6(DjangoModelFactory):
    """Camión #6 — Citroën Jumper, categoría N1, inactivo."""

    class Meta:
        model = "gestion.Camion"
        django_get_or_create = ("patente",)

    patente = "FCT006"
    modelo = "Citroën Jumper"
    categoria = "N1"
    activo = False       # dado de baja → no disponible
    capacidad_volumen_m3 = Decimal("12.00")
    capacidad_peso_kg = Decimal("2200.00")
    anio = 2015
    en_taller = False


# ─────────────────────────────────────────────────────────────────────────────
# Empleado (4 empleados: 2 conductores, 1 ayudante, 1 admin)
# DNI y nro_licencia prefijados con "FCT" para no chocar con los generados
# por los helpers make_empleado() existentes (que usan hash del username).
# ─────────────────────────────────────────────────────────────────────────────

class EmpleadoFactory(DjangoModelFactory):
    """Empleado #1 — Conductor disponible."""

    class Meta:
        model = "gestion.Empleado"
        django_get_or_create = ("dni",)

    user = factory.SubFactory(UserFactory)
    nombre = "Roberto Rodríguez"
    dni = "FCT10000001"
    rol = "CONDUCTOR"
    nro_licencia = "FCT-LC001"
    licencia_fecha_vencimiento = date(2027, 12, 31)
    disponible = True
    art = True


class EmpleadoFactory2(DjangoModelFactory):
    """Empleado #2 — Conductor disponible."""

    class Meta:
        model = "gestion.Empleado"
        django_get_or_create = ("dni",)

    user = factory.SubFactory(UserFactory2)
    nombre = "Marcos López"
    dni = "FCT10000002"
    rol = "CONDUCTOR"
    nro_licencia = "FCT-LC002"
    licencia_fecha_vencimiento = date(2026, 9, 15)
    disponible = True
    art = True


class EmpleadoFactory3(DjangoModelFactory):
    """Empleado #3 — Ayudante de carga disponible."""

    class Meta:
        model = "gestion.Empleado"
        django_get_or_create = ("dni",)

    user = factory.SubFactory(UserFactory3)
    nombre = "Germán Fernández"
    dni = "FCT10000003"
    rol = "AYUDANTE"
    nro_licencia = ""    # los ayudantes no requieren licencia de conducir
    disponible = True
    art = True


class EmpleadoFactory4(DjangoModelFactory):
    """Empleado #4 — Administrativo (no disponible para mudanzas)."""

    class Meta:
        model = "gestion.Empleado"
        django_get_or_create = ("dni",)

    user = factory.SubFactory(UserFactory4)
    nombre = "Karina Vega"
    dni = "FCT10000004"
    rol = "ADMIN"
    nro_licencia = ""
    disponible = False   # administrativo → no asignable a mudanzas
    art = False


# ─────────────────────────────────────────────────────────────────────────────
# TarifaBase (3 presupuestos → necesitamos al menos 1 tarifa activa)
# Nombre prefijado con "[Factory]" para no chocar con "Estándar" ni
# "Tarifa Test Global" / "Tarifa Test Integración" de los conftest.
# ─────────────────────────────────────────────────────────────────────────────

class TarifaBaseFactory(DjangoModelFactory):
    """Tarifa base activa — usada como FK en PresupuestoFactory."""

    class Meta:
        model = "gestion.TarifaBase"
        django_get_or_create = ("nombre",)

    nombre = "[Factory] Tarifa Estándar 2025"
    precio_por_km = Decimal("1200.00")
    precio_ayudante = Decimal("5000.00")
    recargo_piso = Decimal("1500.00")
    recargo_hora_pico = Decimal("1.20")
    recargo_fin_de_semana = Decimal("1.15")
    permite_caba_feriados = False
    activa = True
    vigente_desde = date(2025, 1, 1)
    seguro_camion = Decimal("2000.00")
    empleado_art = Decimal("500.00")
    empleado_seguro_riesgo = Decimal("300.00")
    empleado_seguro_ayudante = Decimal("200.00")
    salario_conductor = Decimal("120000.00")
    salario_ayudante = Decimal("80000.00")


# ─────────────────────────────────────────────────────────────────────────────
# Presupuesto (3 instancias)
# Cada una referencia un cliente y un camión distintos para que las mudanzas
# asociadas no generen conflictos de unicidad (Presupuesto es OneToOne con
# Mudanza).
# ─────────────────────────────────────────────────────────────────────────────

class DireccionOrigenFactory(DjangoModelFactory):
    """Dirección de origen — auxiliar para MudanzaFactory."""

    class Meta:
        model = "gestion.Direccion"

    calle = "Av. Corrientes"
    numero = "1234"
    piso = "PB"
    localidad = "CABA"
    provincia = "Buenos Aires"
    codigo_postal = "1043"
    tiene_ascensor = False


class DireccionDestinoFactory(DjangoModelFactory):
    """Dirección de destino — auxiliar para MudanzaFactory."""

    class Meta:
        model = "gestion.Direccion"

    calle = "Av. Santa Fe"
    numero = "567"
    piso = "2"
    localidad = "CABA"
    provincia = "Buenos Aires"
    codigo_postal = "1059"
    tiene_ascensor = True


class MudanzaBaseFactory(DjangoModelFactory):
    """
    Mudanza base — no instanciar directamente; usar las subclasses numeradas.
    Estado BORRADOR por defecto; las subclasses lo sobreescriben según el
    escenario de cada presupuesto.
    """

    class Meta:
        model = "gestion.Mudanza"

    cliente = factory.SubFactory(ClienteFactory)
    camion = factory.SubFactory(CamionFactory)
    estado = "BORRADOR"
    fecha_hora = factory.LazyFunction(
        lambda: __import__("django.utils.timezone", fromlist=["now"]).now()
        .__class__.now(__import__("django.utils.timezone", fromlist=["now"]))
        # nota: se resuelve en runtime para evitar fechas fijas congeladas
    )
    distancia_km = Decimal("15.00")
    necesita_ayudantes = True
    monto_senia = Decimal("18000.00")
    senia_pagada = False


class MudanzaFactory(DjangoModelFactory):
    """
    Mudanza #1 — estado PRESUPUESTADA, base para PresupuestoFactory.
    Asociada a ClienteFactory + CamionFactory.
    """

    class Meta:
        model = "gestion.Mudanza"

    cliente = factory.SubFactory(ClienteFactory)
    camion = factory.SubFactory(CamionFactory)
    estado = "PRESUPUESTADA"
    fecha_hora = factory.LazyFunction(
        lambda: __import__("django.utils", fromlist=["timezone"]).timezone.now()
        + __import__("datetime").timedelta(days=3)
    )
    distancia_km = Decimal("15.00")
    necesita_ayudantes = True
    monto_senia = Decimal("18000.00")
    senia_pagada = False


class MudanzaFactory2(DjangoModelFactory):
    """
    Mudanza #2 — estado CONFIRMADA con seña pagada.
    Asociada a ClienteFactory2 + CamionFactory2.
    """

    class Meta:
        model = "gestion.Mudanza"

    cliente = factory.SubFactory(ClienteFactory2)
    camion = factory.SubFactory(CamionFactory2)
    estado = "CONFIRMADA"
    fecha_hora = factory.LazyFunction(
        lambda: __import__("django.utils", fromlist=["timezone"]).timezone.now()
        + __import__("datetime").timedelta(days=5)
    )
    distancia_km = Decimal("22.00")
    necesita_ayudantes = True
    monto_senia = Decimal("26400.00")
    senia_pagada = True


class MudanzaFactory3(DjangoModelFactory):
    """
    Mudanza #3 — estado COMPLETADA.
    Asociada a ClienteFactory3 + CamionFactory3.
    """

    class Meta:
        model = "gestion.Mudanza"

    cliente = factory.SubFactory(ClienteFactory3)
    camion = factory.SubFactory(CamionFactory3)
    estado = "COMPLETADA"
    fecha_hora = factory.LazyFunction(
        lambda: __import__("django.utils", fromlist=["timezone"]).timezone.now()
        - __import__("datetime").timedelta(days=2)
    )
    distancia_km = Decimal("9.00")
    necesita_ayudantes = False
    monto_senia = Decimal("10800.00")
    senia_pagada = True


class PresupuestoFactory(DjangoModelFactory):
    """
    Presupuesto #1 — vinculado a MudanzaFactory (PRESUPUESTADA).
    Costos calculados manualmente en base a TarifaBaseFactory:
      distancia:  15 km × $1200 = $18 000
      ayudantes:  1 × $5000     =  $5 000
      camión:     seguro $2000  =  $2 000
      pisos:      sin recargo   =      $0
      total:                      $25 000
      seña (30%):                  $7 500
    """

    class Meta:
        model = "gestion.Presupuesto"

    mudanza = factory.SubFactory(MudanzaFactory)
    tarifa = factory.SubFactory(TarifaBaseFactory)
    costo_distancia = Decimal("18000.00")
    costo_peajes = Decimal("800.00")
    costo_ayudantes = Decimal("5000.00")
    costo_camion = Decimal("2000.00")
    recargo_pisos = Decimal("0.00")
    total = Decimal("25800.00")


class PresupuestoFactory2(DjangoModelFactory):
    """
    Presupuesto #2 — vinculado a MudanzaFactory2 (CONFIRMADA, seña pagada).
    Distancia mayor (22 km) y con recargo de piso.
    """

    class Meta:
        model = "gestion.Presupuesto"

    mudanza = factory.SubFactory(MudanzaFactory2)
    tarifa = factory.SubFactory(TarifaBaseFactory)
    costo_distancia = Decimal("26400.00")   # 22 km × $1200
    costo_peajes = Decimal("1200.00")
    costo_ayudantes = Decimal("5000.00")
    costo_camion = Decimal("2000.00")
    recargo_pisos = Decimal("3000.00")      # piso 2 sin ascensor × $1500
    total = Decimal("37600.00")


class PresupuestoFactory3(DjangoModelFactory):
    """
    Presupuesto #3 — vinculado a MudanzaFactory3 (COMPLETADA, sin ayudantes).
    Distancia corta (9 km), sin ayudantes, sin recargo de piso.
    """

    class Meta:
        model = "gestion.Presupuesto"

    mudanza = factory.SubFactory(MudanzaFactory3)
    tarifa = factory.SubFactory(TarifaBaseFactory)
    costo_distancia = Decimal("10800.00")   # 9 km × $1200
    costo_peajes = Decimal("400.00")
    costo_ayudantes = Decimal("0.00")       # necesita_ayudantes=False
    costo_camion = Decimal("2000.00")
    recargo_pisos = Decimal("0.00")
    total = Decimal("13200.00")
