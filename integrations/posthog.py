from __future__ import annotations

from typing import Any

from core.production_signals import RuntimeSignal, SessionSignal


ENABLED = False
SOURCE = "posthog"


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
        return SessionSignal(
            source=SOURCE,
            event_name=str(event.get("event") or ""),
            raw=str(event),
            metadata={"enabled": ENABLED, **metadata},
        )
    return RuntimeSignal(source=SOURCE, raw=str(event or ""), metadata={"enabled": ENABLED, **metadata})
