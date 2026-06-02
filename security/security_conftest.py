"""
Fixtures compartidas — tier security
Archivo: tests/security/conftest.py

Provee los usuarios de prueba predefinidos y helpers de uso común
en todos los archivos del tier tests/security/.

Usuarios disponibles (fixtures de sesión)
──────────────────────────────────────────
  staff_user    admin_sec / securepass123  — is_staff=True, is_superuser=True
  nostaff_user  nostaff   / pass123        — is_staff=False
  sistema_user  sistema   / —              — is_active=False, para webhooks

Clientes HTTP disponibles
──────────────────────────
  client_staff    — Django TestClient autenticado como admin_sec
  client_nostaff  — Django TestClient autenticado como nostaff
  client_anon     — Django TestClient sin autenticación
  client_csrf     — Django TestClient con enforce_csrf_checks=True, autenticado
"""

import pytest
from django.contrib.auth.models import User
from django.test import Client


# ─────────────────────────────────────────────────────────────────────────────
# Usuarios
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def django_db_setup():
    """Permite usar la DB en fixtures de sesión."""
    pass


@pytest.fixture
def staff_user(db):
    """Usuario staff estándar para tests de seguridad."""
    user, _ = User.objects.get_or_create(
        username="admin_sec",
        defaults={"is_staff": True, "is_superuser": True},
    )
    user.set_password("securepass123")
    user.is_staff = True
    user.is_superuser = True
    user.save()
    return user


@pytest.fixture
def nostaff_user(db):
    """Usuario sin privilegios — bloqueado del panel admin."""
    user, _ = User.objects.get_or_create(
        username="nostaff",
        defaults={"is_staff": False, "is_superuser": False},
    )
    user.set_password("pass123")
    user.is_staff = False
    user.is_superuser = False
    user.save()
    return user


@pytest.fixture
def sistema_user(db):
    """Usuario de sistema para webhooks. is_active=False."""
    user, _ = User.objects.get_or_create(
        username="sistema",
        defaults={"is_active": False},
    )
    user.is_active = False
    user.save()
    return user


# ─────────────────────────────────────────────────────────────────────────────
# Clientes HTTP
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client_staff(staff_user):
    """TestClient autenticado como admin_sec."""
    c = Client()
    c.login(username="admin_sec", password="securepass123")
    return c


@pytest.fixture
def client_nostaff(nostaff_user):
    """TestClient autenticado como nostaff."""
    c = Client()
    c.login(username="nostaff", password="pass123")
    return c


@pytest.fixture
def client_anon():
    """TestClient sin autenticación."""
    return Client()


@pytest.fixture
def client_csrf(staff_user):
    """TestClient con enforce_csrf_checks=True, autenticado como admin_sec."""
    c = Client(enforce_csrf_checks=True)
    c.login(username="admin_sec", password="securepass123")
    return c
