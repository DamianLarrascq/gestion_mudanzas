"""
Fixtures globales — tests/
Archivo: tests/conftest.py

Disponibles en todos los tiers: security/, integration/, e2e/
"""

import pytest
from decimal import Decimal
from datetime import date


@pytest.fixture
def tarifa_activa(db):
    """
    TarifaBase activa mínima. Requerida por cualquier test que llame
    al servicio de presupuesto o al endpoint público /presupuesto/solicitar/.
    """
    from gestion.models.presupuestos import TarifaBase

    tarifa, _ = TarifaBase.objects.get_or_create(
        nombre="Tarifa Test Global",
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


@pytest.fixture
def sistema_user(db):
    """Usuario de sistema para webhooks. Compartido entre tiers."""
    from django.contrib.auth.models import User

    user, _ = User.objects.get_or_create(
        username="sistema",
        defaults={"is_active": False},
    )
    user.is_active = False
    user.save()
    return user
