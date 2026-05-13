"""Minimal Django settings misconfiguration example.

This fails without starting a database or server.
"""

import os

os.environ.pop("DJANGO_SETTINGS_MODULE", None)

from django.conf import settings


settings.configure(
    DEBUG=True,
    SECRET_KEY="manual-test-not-a-real-secret",
    INSTALLED_APPS=["django.contrib.contenttypes"],
    DATABASES={
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    },
)

settings.configure(DEBUG=False)
