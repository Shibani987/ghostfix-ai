from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.feedback import load_feedback
from core.fix_audit import load_fix_audits
from core.incidents import INCIDENTS_DIR, load_incidents


EXPORT_DIR = "exports"
MAX_FIELD_LENGTH = 500
MAX_SNIPPET_LENGTH = 400


EXPORT_FIELDS = [
    "error_type",
    "framework",
    "runtime",
    "language",
    "likely_cause",
    "suggested_fix",
    "confidence",
    "auto_fix_available",
    "rollback_available",
    "resolved_after_fix",
    "feedback_rating",
    "feedback_note",
    "validator_result",
]


def build_stats(root: Optional[Path] = None) -> dict[str, Any]:
    incidents = load_incidents(root)
    feedback = load_feedback(root)
    audits = load_fix_audits(root)

    error_types = Counter(_clean_bucket(row.get("error_type")) for row in incidents)
    frameworks = Counter(_framework(row) for row in incidents)
    feedback_counts = Counter(str(row.get("rating", "")).lower() for row in feedback)

    return {
        "total_incidents": len(incidents),
        "total_successful_diagnoses": sum(1 for row in incidents if _diagnosis_successful(row)),
        "total_auto_fix_attempts": len(audits),
        "total_rollback_events": sum(1 for row in audits if _is_rollback_event(row)),
        "feedback_good": feedback_counts.get("good", 0),
        "feedback_bad": feedback_counts.get("bad", 0),
        "most_common_error_types": _top_counts(error_types),
        "most_common_frameworks": _top_counts(frameworks),
        "dry_run_usage_count": sum(1 for row in audits if "dry-run" in str(row.get("validator_result", "")).lower()),
    }


def export_training_data(root: Optional[Path] = None, *, include_snippets: bool = False) -> tuple[Path, int]:
    base = root or Path.cwd()
    incidents = load_incidents(base)
    feedback_by_incident = _feedback_by_incident(load_feedback(base))
    audits_by_target = _audits_by_target(load_fix_audits(base))

    export_path = _export_path(base)
    export_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with export_path.open("w", encoding="utf-8") as handle:
        for incident in incidents:
            row = _export_row(
                incident,
                feedback_by_incident.get(str(incident.get("timestamp", ""))),
                _latest_audit_for_incident(incident, audits_by_target),
                include_snippets=include_snippets,
            )
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return export_path, count


def sanitize_text(value: Any, *, max_length: int = MAX_FIELD_LENGTH) -> str:
    text = "" if value is None else str(value)
    text = _redact_private_keys(text)
    text = _redact_env_values(text)
    text = _redact_paths(text)
    text = _redact_emails(text)
    text = _redact_tokens(text)
    text = _collapse_long_code(text)
    if len(text) > max_length:
        text = text[:max_length].rstrip() + " <TRUNCATED>"
    return text


def _export_path(root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return root / INCIDENTS_DIR / EXPORT_DIR / f"ghostfix_training_export_{stamp}.jsonl"


def _export_row(incident: dict, feedback: Optional[dict], audit: Optional[dict], *, include_snippets: bool) -> dict:
    row = {
        "error_type": sanitize_text(incident.get("error_type")),
        "framework": sanitize_text(_framework(incident)),
        "runtime": sanitize_text(incident.get("runtime") or "unknown"),
        "language": sanitize_text(incident.get("language") or "unknown"),
        "likely_cause": sanitize_text(incident.get("cause")),
        "suggested_fix": sanitize_text(incident.get("fix")),
        "confidence": _confidence(incident.get("confidence")),
        "auto_fix_available": bool(incident.get("auto_fix_available", False)),
        "rollback_available": bool((incident.get("rollback_metadata") or {}).get("backup") or (audit or {}).get("rollback_available")),
        "resolved_after_fix": bool(incident.get("resolved_after_fix", False)),
        "feedback_rating": sanitize_text((feedback or {}).get("rating")),
        "feedback_note": sanitize_text((feedback or {}).get("note")),
        "validator_result": sanitize_text((audit or {}).get("validator_result")),
    }
    if include_snippets:
        snippet = incident.get("snippet") or incident.get("context") or incident.get("code_context") or ""
        row["snippet"] = sanitize_text(snippet, max_length=MAX_SNIPPET_LENGTH)
    return row


def _feedback_by_incident(rows: list[dict]) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for row in rows:
        incident_id = row.get("latest_incident_id")
        if incident_id:
            indexed[str(incident_id)] = row
    return indexed


def _audits_by_target(rows: list[dict]) -> dict[str, list[dict]]:
    indexed: dict[str, list[dict]] = {}
    for row in rows:
        target = str(row.get("target_file", ""))
        if target:
            indexed.setdefault(target, []).append(row)
    return indexed


def _latest_audit_for_incident(incident: dict, audits_by_target: dict[str, list[dict]]) -> Optional[dict]:
    target = str(incident.get("file", ""))
    if not target:
        return None
    rows = audits_by_target.get(target) or audits_by_target.get(str(Path(target)))
    return rows[-1] if rows else None


def _diagnosis_successful(row: dict) -> bool:
    return bool(row.get("error_type") and (row.get("cause") or row.get("fix")))


def _is_rollback_event(row: dict) -> bool:
    return "rollback completed" in str(row.get("validator_result", "")).lower()


def _top_counts(counter: Counter) -> list[dict[str, Any]]:
    return [
        {"value": value, "count": count}
        for value, count in counter.most_common(5)
        if value and value != "unknown"
    ]


def _framework(row: dict) -> str:
    return _clean_bucket(row.get("framework") or row.get("runtime") or "unknown")


def _clean_bucket(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    return text or "unknown"


def _confidence(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if 0 <= number <= 1:
        number *= 100
    return max(0, min(100, int(round(number))))


def _redact_env_values(text: str) -> str:
    return re.sub(
        r"(?im)^([A-Z_][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|AUTH|CREDENTIAL)[A-Z0-9_]*\s*=\s*)(.+)$",
        lambda match: f"{match.group(1)}<REDACTED>",
        text,
    )


def _redact_private_keys(text: str) -> str:
    return re.sub(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        "<REDACTED_PRIVATE_KEY>",
        text,
        flags=re.DOTALL,
    )


def _redact_paths(text: str) -> str:
    text = re.sub(r"[A-Za-z]:\\Users\\[^\\\s\"']+(?:\\[^\s\"']*)?", "<HOME_PATH>", text)
    text = re.sub(r"/home/[^/\s\"']+(?:/[^\s\"']*)?", "<HOME_PATH>", text)
    text = re.sub(r"/Users/[^/\s\"']+(?:/[^\s\"']*)?", "<HOME_PATH>", text)
    text = re.sub(r"[A-Za-z]:\\[^\s\"']+", "<ABSOLUTE_PATH>", text)
    text = re.sub(r"(?<![\w.])/(?:var|tmp|etc|opt|srv|workspace|mnt)/[^\s\"']+", "<ABSOLUTE_PATH>", text)
    return text


def _redact_emails(text: str) -> str:
    return re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "<EMAIL>", text)


def _redact_tokens(text: str) -> str:
    text = re.sub(
        r"(?i)\b([A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|AUTHORIZATION)[A-Z0-9_]*)\b\s*[:=]\s*['\"]?[^'\"\s,;]+",
        lambda match: f"{match.group(1)}=<REDACTED>",
        text,
    )
    text = re.sub(r"\b(?:sk|pk|ghp|github_pat|xoxb|xoxp)_[A-Za-z0-9_=-]{12,}\b", "<REDACTED_TOKEN>", text)
    text = re.sub(r"\b[A-Za-z0-9_=-]{32,}\b", "<REDACTED_TOKEN>", text)
    return text


def _collapse_long_code(text: str) -> str:
    lines = text.splitlines()
    if len(lines) > 12:
        return "\n".join(lines[:12]) + "\n<TRUNCATED_CODE>"
    return text
