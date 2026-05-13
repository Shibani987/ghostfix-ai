"""Small Flask shop with intentional runtime failures."""

from __future__ import annotations

import os
import sys


class TemplateNotFound(Exception):
    pass


def _scenario() -> str:
    if "--scenario" in sys.argv:
        index = sys.argv.index("--scenario")
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return os.getenv("GHOSTFIX_SCENARIO", "template_not_found")


def _template_not_found() -> None:
    raise TemplateNotFound("shop/checkout.html")


def _missing_dependency() -> None:
    import missing_stripe_client

    print(missing_stripe_client)


def _route_exception() -> None:
    cart = {"items": []}
    total = cart["total"]
    print(total)


def main() -> None:
    scenario = _scenario()
    if scenario == "template_not_found":
        _template_not_found()
    elif scenario == "missing_dependency":
        _missing_dependency()
    elif scenario == "route_exception":
        _route_exception()
    else:
        raise RuntimeError(f"Unknown Flask fixture scenario: {scenario}")


if __name__ == "__main__":
    main()
