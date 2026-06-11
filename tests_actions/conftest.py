import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("SECRET_KEY", "ci-test-secret-key-only-for-github-actions")
os.environ.setdefault("DEBUG", "True")
os.environ.setdefault("DB_ENGINE", "sqlite")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "True")
