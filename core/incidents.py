from __future__ import annotations

import json
import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


INCIDENTS_DIR = ".ghostfix"
INCIDENTS_FILE = "incidents.jsonl"


@dataclass
class Incident:
    timestamp: str
    command: str
    file: str
    language: str
    runtime: str
    error_type: str
    cause: str
    fix: str
    confidence: int
    auto_fix_available: bool
    resolved_after_fix: bool
    rollback_metadata: dict = field(default_factory=dict)


def incidents_path(root: Optional[Path] = None) -> Path:
    base = root or Path.cwd()
    return base / INCIDENTS_DIR / INCIDENTS_FILE


def make_incident(
    *,
    command: str,
    file: str = "",
    language: str = "unknown",
    runtime: str = "unknown",
    error_type: str = "",
    cause: str = "",
    fix: str = "",
    confidence: int | float = 0,
    auto_fix_available: bool = False,
    resolved_after_fix: bool = False,
    rollback_metadata: Optional[dict] = None,
) -> Incident:
    return Incident(
        timestamp=datetime.now().isoformat(timespec="seconds"),
        command=command or "",
        file=file or "",
        language=language or "unknown",
        runtime=runtime or "unknown",
        error_type=error_type or "",
        cause=cause or "",
        fix=fix or "",
        confidence=_normalize_confidence(confidence),
        auto_fix_available=bool(auto_fix_available),
        resolved_after_fix=bool(resolved_after_fix),
        rollback_metadata=rollback_metadata or {},
    )


def record_incident(incident: Incident, root: Optional[Path] = None) -> bool:
    """Append an incident unless it repeats the latest recorded incident."""
    path = incidents_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)

    latest = _last_incident(path)
    if latest and _fingerprint(latest) == _fingerprint(asdict(incident)):
        return False

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(incident), ensure_ascii=False) + "\n")
    return True


def load_incidents(root: Optional[Path] = None, last: Optional[int] = None) -> list[dict]:
    path = incidents_path(root)
    if not path.exists():
        return []

    rows = list(_read_jsonl(path))
    if last is not None:
        return rows[-max(last, 0):]
    return rows


def _read_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield value


def _last_incident(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    latest = None
    for row in _read_jsonl(path):
        latest = row
    return latest


def _fingerprint(row: dict) -> str:
    stable = {
        "command": row.get("command", ""),
        "file": row.get("file", ""),
        "language": row.get("language", ""),
        "runtime": row.get("runtime", ""),
        "error_type": row.get("error_type", ""),
        "cause": row.get("cause", ""),
        "fix": row.get("fix", ""),
        "auto_fix_available": bool(row.get("auto_fix_available", False)),
        "resolved_after_fix": bool(row.get("resolved_after_fix", False)),
    }
    raw = json.dumps(stable, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_confidence(value: int | float) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if 0 <= number <= 1:
        number *= 100
    return max(0, min(100, int(round(number))))
