#!/usr/bin/env python3
"""Prediction helper for GhostFix Brain v2 with hard auto-fix safety guards."""

from __future__ import annotations

import argparse
import json
import math
import pickle
import re
from pathlib import Path
from typing import Any

try:
    from ml.train_ghostfix_brain import build_input
except ImportError:
    from train_ghostfix_brain import build_input


DEFAULT_MODEL = Path("ml/models/ghostfix_brain_v2.pkl")
BLOCKED_AUTO_FIX_ERROR_TYPES = {"FileNotFoundError", "PermissionError", "RuntimeError"}
BLOCKED_AUTO_FIX_COMPLEXITY = {"needs_project_context", "unsafe_to_autofix"}
AUTO_FIX_CONFIDENCE_THRESHOLD = 0.95


def load_model(model_path: Path = DEFAULT_MODEL) -> dict[str, Any]:
    with model_path.open("rb") as handle:
        artifact = pickle.load(handle)
    if "models" not in artifact:
        raise ValueError(f"{model_path} is not a GhostFix Brain v2 artifact")
    return artifact


def probability_for(model: Any, text: str, label: str) -> float:
    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba([text])[0]
        classes = list(model.classes_)
        try:
            return float(probabilities[classes.index(label)])
        except ValueError:
            return 0.0

    if hasattr(model, "decision_function"):
        scores = model.decision_function([text])
        classes = list(model.classes_)
        try:
            class_index = classes.index(label)
        except ValueError:
            return 0.5
        raw_scores = scores[0] if hasattr(scores, "__len__") else scores
        raw_score = raw_scores[class_index] if hasattr(raw_scores, "__len__") else raw_scores
        try:
            return 1.0 / (1.0 + math.exp(-float(raw_score)))
        except OverflowError:
            return 1.0 if raw_score > 0 else 0.0

    return 0.5


def predict_label(model: Any, text: str) -> tuple[str, float]:
    label = str(model.predict([text])[0])
    return label, round(probability_for(model, text, label), 4)


def is_empty_json_loads_pattern(error_type: str, text: str, failing_line: str) -> bool:
    if error_type != "JSONDecodeError" or not re.search(r"\bjson\.loads\s*\(", text):
        return False
    if not re.search(r"Expecting value: line 1 column \d+ \(char [03]\)", text):
        return False

    parsed_name_match = re.search(r"json\.loads\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", failing_line or "")
    parsed_name = parsed_name_match.group(1) if parsed_name_match else ""
    if parsed_name:
        empty_assignment = rf"\b{re.escape(parsed_name)}\s*=\s*['\"]\s*['\"]"
        if re.search(empty_assignment, text):
            return True

    return bool(re.search(r"\b(empty json|empty input|empty string|contains only whitespace)\b", text, re.IGNORECASE))


def is_missing_colon_syntax_pattern(error_type: str, text: str, failing_line: str) -> bool:
    if error_type != "SyntaxError" or "expected ':'" not in text.lower():
        return False
    line = (failing_line or "").strip()
    starters = ("if ", "elif ", "else", "for ", "while ", "def ", "class ", "try", "except", "finally", "with ", "match ")
    return line.startswith(starters) and not line.endswith(":")


def is_allowed_simple_auto_fix(error_type: str, complexity: str, text: str, failing_line: str) -> bool:
    if complexity != "deterministic_safe":
        return False
    return is_empty_json_loads_pattern(error_type, text, failing_line) or is_missing_colon_syntax_pattern(error_type, text, failing_line)


def apply_auto_fix_safety_guard(
    raw_prediction: dict[str, str],
    confidence: dict[str, float],
    text: str,
    failing_line: str,
) -> tuple[str, list[str]]:
    guarded = raw_prediction["auto_fix_safety"]
    reasons: list[str] = []

    if raw_prediction["complexity"] in BLOCKED_AUTO_FIX_COMPLEXITY:
        guarded = "not_safe"
        reasons.append("blocked_complexity")
    if raw_prediction["error_type"] in BLOCKED_AUTO_FIX_ERROR_TYPES:
        guarded = "not_safe"
        reasons.append("blocked_error_type")
    if confidence["auto_fix_safety"] < AUTO_FIX_CONFIDENCE_THRESHOLD:
        guarded = "not_safe"
        reasons.append("low_auto_fix_safety_confidence")
    if not is_allowed_simple_auto_fix(raw_prediction["error_type"], raw_prediction["complexity"], text, failing_line):
        guarded = "not_safe"
        reasons.append("not_allowed_simple_auto_fix_pattern")

    return guarded, sorted(set(reasons))


def predict_record(
    record: dict[str, Any],
    model_path: Path = DEFAULT_MODEL,
    artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if artifact is None:
        artifact = load_model(model_path)
    models = artifact["models"]
    text = build_input(record)

    required_heads = {"error_type", "fix_template", "complexity", "auto_fix_safety"}
    missing_heads = sorted(required_heads - set(models))
    if missing_heads:
        raise ValueError(f"{model_path} is missing Brain v2 heads: {missing_heads}")

    raw_prediction: dict[str, str] = {}
    confidence: dict[str, float] = {}
    for task in sorted(required_heads):
        raw_prediction[task], confidence[task] = predict_label(models[task], text)

    guarded_auto_fix_safety, guard_reasons = apply_auto_fix_safety_guard(
        raw_prediction,
        confidence,
        text,
        str(record.get("failing_line") or ""),
    )
    guarded_prediction = dict(raw_prediction)
    guarded_prediction["auto_fix_safety"] = guarded_auto_fix_safety

    return {
        "raw_prediction": raw_prediction,
        "guarded_prediction": guarded_prediction,
        "fix_template_text": artifact.get("fix_templates", {}).get(
            guarded_prediction.get("fix_template", ""),
            guarded_prediction.get("fix_template", ""),
        ),
        "confidence": confidence,
        "auto_fix_safety_guard_applied": guarded_auto_fix_safety != raw_prediction["auto_fix_safety"],
        "auto_fix_safety_guard_reasons": guard_reasons,
        "source": "ghostfix_brain_v2",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Predict with GhostFix Brain v2 safety guard. Runtime is not updated.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--error", default="")
    parser.add_argument("--message", default="")
    parser.add_argument("--context", default="")
    parser.add_argument("--failing-line", default="")
    args = parser.parse_args()

    record = {
        "error": args.error,
        "message": args.message,
        "context": args.context,
        "failing_line": args.failing_line,
    }
    print(json.dumps(predict_record(record, args.model), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
