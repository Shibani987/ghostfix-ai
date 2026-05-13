from importlib import import_module


DJANGO_SETTINGS_MODULE = "company_portal.settings.local"

settings = import_module(DJANGO_SETTINGS_MODULE)
print(settings.SECRET_KEY)
