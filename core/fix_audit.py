from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.incidents import INCIDENTS_DIR


FIX_AUDIT_FILE = "fix_audit.jsonl"


def fix_audit_path(root: Optional[Path] = None) -> Path:
    base = root or Path.cwd()
    return base / INCIDENTS_DIR / FIX_AUDIT_FILE


def record_fix_audit(
    *,
    target_file: str,
    backup_path: str = "",
    patch: str = "",
    validator_result: str = "",
    rollback_available: bool = False,
    user_confirmed: bool = False,
    root: Optional[Path] = None,
) -> dict:
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "target_file": target_file or "",
        "backup_path": backup_path or "",
        "patch_summary": _patch_summary(patch),
        "validator_result": validator_result or "",
        "rollback_available": bool(rollback_available),
        "user_confirmed": bool(user_confirmed),
    }
    path = fix_audit_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def load_fix_audits(root: Optional[Path] = None, last: Optional[int] = None) -> list[dict]:
    path = fix_audit_path(root)
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
    if last is not None:
        return rows[-max(last, 0):]
    return rows


def _patch_summary(patch: str) -> str:
    if not patch:
        return ""
    changed = [
        line
        for line in str(patch).splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    summary = " | ".join(changed[:4])
    return summary[:500]
