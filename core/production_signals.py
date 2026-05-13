from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeSignal:
    source: str = "local_log"
    raw: str = ""
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthSignal(RuntimeSignal):
    status_code: int | None = None
    user_id: str | None = None
    endpoint: str = ""
    reason: str = ""


@dataclass
class HttpSignal(RuntimeSignal):
    method: str = ""
    endpoint: str = ""
    status_code: int | None = None
    latency_ms: float | None = None


@dataclass
class SessionSignal(RuntimeSignal):
    session_id: str | None = None
    user_id: str | None = None
    event_name: str = ""


@dataclass
class ErrorSignal(RuntimeSignal):
    error_type: str = ""
    message: str = ""
    traceback: str = ""
    file: str = ""
