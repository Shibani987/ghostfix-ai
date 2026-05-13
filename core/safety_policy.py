from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.confidence import normalize_confidence


SAFE_COMPLEXITY = "deterministic_safe"
SAFE_ERROR_TYPES = {"SyntaxError", "IndentationError", "JSONDecodeError"}
NEVER_AUTO_FIX_COMPLEXITIES = {"needs_project_context", "unsafe_to_autofix"}
NEVER_AUTO_FIX_ERROR_TYPES = {"FileNotFoundError", "PermissionError", "RuntimeError"}
MIN_AUTO_FIX_CONFIDENCE = 0.95


@dataclass
class SafetyDecision:
    auto_fix_allowed: bool
    reason: str
    manual_review_required: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_fix_allowed": self.auto_fix_allowed,
            "reason": self.reason,
            "manual_review_required": self.manual_review_required,
        }


def evaluate_auto_fix_policy(
    *,
    error_type: str | None,
    complexity_class: str | None,
    confidence: int | float | str | None,
    patch_available: bool = False,
    patch_valid: bool = False,
    brain_auto_fix_safety: str | None = None,
    fix_kind: str = "model_suggested_fix",
) -> SafetyDecision:
    """Strict production auto-fix gate.

    This policy is intentionally conservative. Models can explain and rank
    fixes, but they do not grant auto-fix permission.
    """

    error_type = error_type or ""
    complexity_class = complexity_class or ""
    confidence_value = normalize_confidence(confidence)

    if complexity_class in NEVER_AUTO_FIX_COMPLEXITIES:
        return SafetyDecision(False, f"Auto-fix blocked for complexity_class={complexity_class}.", True)
    if error_type in NEVER_AUTO_FIX_ERROR_TYPES:
        return SafetyDecision(False, f"Auto-fix blocked for error_type={error_type}.", True)
    if brain_auto_fix_safety in {"not_safe", "unsafe"}:
        return SafetyDecision(False, "Brain safety guard marked this case not safe.", True)
    if complexity_class != SAFE_COMPLEXITY:
        return SafetyDecision(False, "Manual review required: complexity is not deterministic_safe.", True)
    if error_type not in SAFE_ERROR_TYPES:
        return SafetyDecision(False, f"Manual review required: {error_type} is not an allowed auto-fix error type.", True)
    if not patch_available:
        return SafetyDecision(False, "Auto-fix blocked because no deterministic patch is available.", True)
    if not patch_valid:
        return SafetyDecision(False, "Auto-fix blocked because patch validation failed.", True)
    if fix_kind == "deterministic_verified_fix" and error_type in {"SyntaxError", "IndentationError"}:
        return SafetyDecision(
            True,
            "deterministic verified syntax fix",
            False,
        )
    if confidence_value < MIN_AUTO_FIX_CONFIDENCE:
        return SafetyDecision(False, "Manual review required: confidence is below 0.95.", True)

    return SafetyDecision(
        True,
        "Auto-fix allowed by strict policy: deterministic_safe, high confidence, validated patch.",
        False,
    )
