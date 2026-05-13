from __future__ import annotations

from typing import Any

from core.production_signals import ErrorSignal, RuntimeSignal


ENABLED = False
SOURCE = "sentry"


def parse_event(event: Any = None, **metadata: Any) -> dict[str, Any]:
    return {
        "enabled": ENABLED,
        "source": SOURCE,
        "raw": event or {},
        "metadata": metadata,
        "signals": [],
    }


def normalize_event(event: Any = None, **metadata: Any) -> RuntimeSignal:
    if isinstance(event, dict):
        message = str(event.get("message") or event.get("error") or "")
        return ErrorSignal(source=SOURCE, message=message, raw=str(event), metadata={"enabled": ENABLED, **metadata})
    return RuntimeSignal(source=SOURCE, raw=str(event or ""), metadata={"enabled": ENABLED, **metadata})
