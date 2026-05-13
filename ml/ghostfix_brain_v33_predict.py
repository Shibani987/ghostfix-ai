#!/usr/bin/env python3
"""Prediction helper for GhostFix Brain v3.3 experimental opt-in."""

from __future__ import annotations

import argparse
import importlib
import json
import pickle
import sys
from pathlib import Path
from typing import Any

try:
    from ml.brain_v3_features import ERROR_TYPE_TEMPLATE_MAP
    from ml.ghostfix_brain_v2_predict import apply_auto_fix_safety_guard
    from ml.train_ghostfix_brain import build_input
except ImportError:
    from brain_v3_features import ERROR_TYPE_TEMPLATE_MAP
    from ghostfix_brain_v2_predict import apply_auto_fix_safety_guard
    from train_ghostfix_brain import build_input


DEFAULT_MODEL = Path("ml/models/ghostfix_brain_v33.pkl")
REQUIRED_HEADS = {"error_type", "fix_template", "complexity_class", "auto_fix_safety"}


def register_pickle_module_aliases() -> None:
    """Support artifacts pickled from both repo-root and package imports."""

    aliases = {
        "brain_v3_features": "ml.brain_v3_features",
        "train_ghostfix_brain": "ml.train_ghostfix_brain",
    }
    for legacy_name, package_name in aliases.items():
        if legacy_name not in sys.modules:
            sys.modules[legacy_name] = importlib.import_module(package_name)


def load_model(model_path: Path = DEFAULT_MODEL) -> dict[str, Any]:
    register_pickle_module_aliases()
    with model_path.open("rb") as handle:
        artifact = pickle.load(handle)
    if "models" not in artifact:
        raise ValueError(f"{model_path} is not a GhostFix Brain v3.3 artifact")
    missing = sorted(REQUIRED_HEADS - set(artifact["models"]))
    if missing:
        raise ValueError(f"{model_path} is missing v3.3 heads: {missing}")
    return artifact


def probability_for(model: Any, text: str, label: str) -> float:
    if not hasattr(model, "predict_proba"):
        return 0.5
    classes = list(model.classes_)
    try:
        probabilities = model.predict_proba([text])[0]
        return float(probabilities[classes.index(label)]) if label in classes else 0.0
    except Exception:
        return 0.0


def predict_label(model: Any, text: str) -> tuple[str, float]:
    label = str(model.predict([text])[0])
    return label, round(probability_for(model, text, label), 4)


def apply_fix_template_compatibility_guard(
    raw_prediction: dict[str, str],
    confidence: dict[str, float],
) -> tuple[dict[str, str], dict[str, float], list[str]]:
    guarded = dict(raw_prediction)
    guarded_confidence = dict(confidence)
    reasons: list[str] = []
    expected_template = ERROR_TYPE_TEMPLATE_MAP.get(guarded.get("error_type", ""))
    if expected_template and guarded.get("fix_template") != expected_template:
        guarded["fix_template"] = expected_template
        guarded_confidence["fix_template"] = min(float(guarded_confidence.get("fix_template", 0.0)), 0.5)
        reasons.append("corrected_incompatible_fix_template")
    return guarded, guarded_confidence, reasons


def predict_record(
    record: dict[str, Any],
    model_path: Path = DEFAULT_MODEL,
    artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if artifact is None:
        artifact = load_model(model_path)
    text = build_input(record)
    models = artifact["models"]

    raw_prediction: dict[str, str] = {}
    confidence: dict[str, float] = {}
    for task in sorted(REQUIRED_HEADS):
        raw_prediction[task], confidence[task] = predict_label(models[task], text)

    compatible_prediction, compatible_confidence, compatibility_reasons = apply_fix_template_compatibility_guard(
        raw_prediction,
        confidence,
    )

    guard_input = {
        "error_type": compatible_prediction["error_type"],
        "fix_template": compatible_prediction["fix_template"],
        "complexity": compatible_prediction["complexity_class"],
        "auto_fix_safety": compatible_prediction["auto_fix_safety"],
    }
    guard_confidence = {
        "error_type": compatible_confidence["error_type"],
        "fix_template": compatible_confidence["fix_template"],
        "complexity": compatible_confidence["complexity_class"],
        "auto_fix_safety": compatible_confidence["auto_fix_safety"],
    }
    guarded_auto_fix_safety, guard_reasons = apply_auto_fix_safety_guard(
        guard_input,
        guard_confidence,
        text,
        str(record.get("failing_line") or ""),
    )
    guarded_prediction = dict(compatible_prediction)
    guarded_prediction["auto_fix_safety"] = guarded_auto_fix_safety
    guard_reasons = sorted(set(guard_reasons + compatibility_reasons))

    return {
        "raw_prediction": raw_prediction,
        "guarded_prediction": guarded_prediction,
        "fix_template_text": artifact.get("fix_templates", {}).get(
            guarded_prediction.get("fix_template", ""),
            guarded_prediction.get("fix_template", ""),
        ),
        "confidence": compatible_confidence,
        "auto_fix_safety_guard_applied": (
            guarded_auto_fix_safety != raw_prediction["auto_fix_safety"]
            or bool(compatibility_reasons)
        ),
        "auto_fix_safety_guard_reasons": guard_reasons,
        "source": "ghostfix_brain_v33",
        "brain_version": "v3.3-experimental",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Predict with GhostFix Brain v3.3 experimental model.")
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
