"""Confidence helpers for GhostFix runtime.

Internal runtime confidence is always normalized to 0.0-1.0.
User-facing output should render it as a 0-100 percentage.
"""

from __future__ import annotations


def normalize_confidence(value: int | float | str | None) -> float:
    """Return confidence on the internal 0.0-1.0 scale."""
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if number > 1.0:
        number /= 100.0
    return max(0.0, min(1.0, number))


def confidence_percent(value: int | float | str | None) -> int:
    """Return confidence as a display percentage."""
    return int(round(normalize_confidence(value) * 100))
