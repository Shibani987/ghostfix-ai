"""Minimal Django settings with an intentionally missing app."""

SECRET_KEY = "manual-test-not-a-real-secret"
DEBUG = True
ROOT_URLCONF = "project.urls"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "missing_inventory_app",
]

MIDDLEWARE = []
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
