import sys


class ImproperlyConfigured(Exception):
    pass


ImproperlyConfigured.__module__ = "django.core.exceptions"


def execute_from_command_line(argv):
    if len(argv) > 1 and argv[1] == "runserver":
        load_settings()


def load_settings():
    raise ImproperlyConfigured("DJANGO_SETTINGS_MODULE points to missing project.settings.local")


if __name__ == "__main__":
    execute_from_command_line(sys.argv)
