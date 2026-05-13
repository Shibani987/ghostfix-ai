"""Tiny Django-like blog entrypoint with intentional startup failures."""

from __future__ import annotations

import importlib
import os
import sys


class TemplateDoesNotExist(Exception):
    pass


def _scenario() -> str:
    if "--scenario" in sys.argv:
        index = sys.argv.index("--scenario")
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return os.getenv("GHOSTFIX_SCENARIO", "bad_installed_apps")


def _bad_installed_apps() -> None:
    settings = importlib.import_module("blog.settings")
    for app_name in settings.INSTALLED_APPS:
        importlib.import_module(app_name)


def _missing_settings_import() -> None:
    importlib.import_module("blog.settings_import_failure")


def _missing_template() -> None:
    raise TemplateDoesNotExist("blog/post_detail.html")


def main() -> None:
    scenario = _scenario()
    if scenario == "bad_installed_apps":
        _bad_installed_apps()
    elif scenario == "missing_settings_import":
        _missing_settings_import()
    elif scenario == "missing_template":
        _missing_template()
    else:
        raise RuntimeError(f"Unknown Django fixture scenario: {scenario}")


if __name__ == "__main__":
    main()
