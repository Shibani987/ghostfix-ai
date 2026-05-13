#!/usr/bin/env python3
"""Append-only feedback logging for GhostFix interactions."""

from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


FEEDBACK_LOG = Path(".ml/feedback/ghostfix_feedback.jsonl")
LEGACY_FEEDBACK_LOG = Path("ml/feedback_logs.jsonl")


def _context_text(context: Any) -> str:
    if isinstance(context, dict):
        return context.get("snippet") or context.get("context") or json.dumps(context, ensure_ascii=False)
    return context or ""


def _decision_value(decision: Any, key: str, default: Any = "") -> Any:
    if decision is None:
        return default
    if isinstance(decision, dict):
        return decision.get(key, default)
    return getattr(decision, key, default)


def _mask_sensitive(text: str) -> str:
    text = text or ""
    text = re.sub(r"\bAKIA[0-9A-Z]{16}\b", "[AWS_KEY]", text)
    text = re.sub(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b", "[GITHUB_TOKEN]", text)
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s]+", r"\1=[REDACTED]", text)
    return text


def _traceback_hash(error: str) -> str:
    normalized = re.sub(r'File ".*?", line \d+', 'File "FILE", line LINE', _mask_sensitive(error or ""))
    return hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()[:24]


def log_feedback(
    *,
    error: str,
    error_type: str,
    context: Any,
    suggested_fix: str,
    accepted: bool,
    auto_fix_attempted: bool,
    success_after_fix: bool,
    brain_type: str = "",
    brain_confidence: int | float = 0,
    source: str = "hybrid",
    cause: str = "",
    brain_fix_template: str = "",
    complexity_class: str = "",
    auto_fix_allowed: bool = False,
    guard_applied: bool = False,
    path: Optional[Path] = None,
) -> dict:
    """Write one interaction feedback record to JSONL."""
    record = {
        "error_type": error_type or "",
        "traceback_hash": _traceback_hash(error),
        "source": source,
        "brain_type": brain_type or "",
        "brain_confidence": brain_confidence or 0,
        "predicted_fix_template": brain_fix_template or "",
        "confidence": brain_confidence or 0,
        "complexity_class": complexity_class or "",
        "auto_fix_allowed": bool(auto_fix_allowed),
        "guard_applied": bool(guard_applied),
        "accepted": bool(accepted),
        "auto_fix_attempted": bool(auto_fix_attempted),
        "success_after_fix": bool(success_after_fix),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    output = path or FEEDBACK_LOG
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def log_decision_feedback(
    *,
    parsed_error: dict,
    context: Any,
    decision: Any,
    accepted: bool,
    auto_fix_attempted: bool,
    success_after_fix: bool,
) -> dict:
    """Convenience wrapper for core Decision objects."""
    return log_feedback(
        error=parsed_error.get("raw", ""),
        error_type=parsed_error.get("type", ""),
        context=context,
        suggested_fix=_decision_value(decision, "fix", ""),
        cause=_decision_value(decision, "cause", ""),
        source="hybrid",
        brain_type=_decision_value(decision, "brain_type", ""),
        brain_confidence=_decision_value(decision, "brain_confidence", 0),
        brain_fix_template=_decision_value(decision, "brain_fix_template", ""),
        complexity_class=_decision_value(decision, "complexity_class", ""),
        auto_fix_allowed=bool(_decision_value(decision, "auto_fix_available", False)),
        guard_applied=bool(_decision_value(decision, "guard_applied", False)),
        accepted=accepted,
        auto_fix_attempted=auto_fix_attempted,
        success_after_fix=success_after_fix,
    )
