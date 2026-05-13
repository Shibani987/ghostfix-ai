from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.incidents import INCIDENTS_DIR, load_incidents


FEEDBACK_FILE = "feedback.jsonl"


def feedback_path(root: Optional[Path] = None) -> Path:
    base = root or Path.cwd()
    return base / INCIDENTS_DIR / FEEDBACK_FILE


def save_feedback(rating: str, note: str = "", root: Optional[Path] = None) -> dict:
    latest = _latest_incident_summary(root)
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "rating": rating,
        "note": note or "",
        "latest_incident_id": latest.get("id") if latest else None,
        "incident": latest,
    }

    path = feedback_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def load_feedback(root: Optional[Path] = None) -> list[dict]:
    path = feedback_path(root)
    if not path.exists():
        return []

    rows = []
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
                rows.append(value)
    return rows


def _latest_incident_summary(root: Optional[Path] = None) -> Optional[dict]:
    rows = load_incidents(root, last=1)
    if not rows:
        return None

    latest = rows[0]
    incident_id = latest.get("timestamp") or ""
    return {
        "id": incident_id,
        "timestamp": latest.get("timestamp", ""),
        "command": latest.get("command", ""),
        "file": latest.get("file", ""),
        "runtime": latest.get("runtime", ""),
        "error_type": latest.get("error_type", ""),
        "cause": latest.get("cause", ""),
        "fix": latest.get("fix", ""),
        "confidence": latest.get("confidence", 0),
        "auto_fix_available": bool(latest.get("auto_fix_available", False)),
        "resolved_after_fix": bool(latest.get("resolved_after_fix", False)),
    }
