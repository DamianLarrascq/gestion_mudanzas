"""
Tests — Celery y configuración del proyecto
Archivo: tests/test_celery.py

Verifica la configuración de Celery (config/celery.py) y que
las tareas se descubren correctamente.
"""
from django.test import TestCase, override_settings


class CeleryConfigTest(TestCase):

    def test_celery_app_importable(self):
        """La app de Celery debe importarse correctamente."""
        from config.celery import app
        self.assertIsNotNone(app)
        self.assertEqual(app.main, "mudanzas")

    def test_broker_url_configurado(self):
        """CELERY_BROKER_URL debe estar presente en settings."""
        from django.conf import settings
        broker = getattr(settings, "CELERY_BROKER_URL", None)
        self.assertIsNotNone(broker)
        self.assertIn("redis", broker.lower())

    def test_serializer_es_json(self):
        """Celery debe usar JSON como serializador (seguridad)."""
        from django.conf import settings
        self.assertEqual(getattr(settings, "CELERY_TASK_SERIALIZER", None), "json")
        self.assertEqual(getattr(settings, "CELERY_RESULT_SERIALIZER", None), "json")

    def test_timezone_configurado(self):
        """El timezone de Celery debe ser Argentina."""
        from django.conf import settings
        tz = getattr(settings, "CELERY_TIMEZONE", None)
        self.assertEqual(tz, "America/Argentina/Buenos_Aires")

    def test_autodiscover_tasks_no_falla(self):
        """autodiscover_tasks() no debe lanzar excepciones."""
        from config.celery import app
        try:
            app.autodiscover_tasks()
        except Exception as e:
            self.fail(f"autodiscover_tasks() lanzó excepción: {e}")


class DjangoSettingsTest(TestCase):
    """Verifica settings críticos del proyecto."""

    def test_apps_instaladas_incluyen_modulos_del_proyecto(self):
        from django.conf import settings
        for app in ["gestion", "webhook", "notificaciones", "public", "unfold"]:
            self.assertIn(app, settings.INSTALLED_APPS,
                          f"App '{app}' no está en INSTALLED_APPS")

    def test_middleware_csrf_activo(self):
        from django.conf import settings
        csrf_mw = "django.middleware.csrf.CsrfViewMiddleware"
        self.assertIn(csrf_mw, settings.MIDDLEWARE)

    def test_middleware_xframe_activo(self):
        from django.conf import settings
        xframe = "django.middleware.clickjacking.XFrameOptionsMiddleware"
        self.assertIn(xframe, settings.MIDDLEWARE)

    def test_url_raiz_apunta_a_admin(self):
        from django.conf import settings
        self.assertEqual(settings.ROOT_URLCONF, "config.urls")

    def test_admin_url_accesible(self):
        response = self.client.get("/admin/login/")
        self.assertEqual(response.status_code, 200)

    def test_pagina_inexistente_devuelve_404(self):
        response = self.client.get("/esta-ruta-no-existe-nunca/")
        self.assertEqual(response.status_code, 404)
