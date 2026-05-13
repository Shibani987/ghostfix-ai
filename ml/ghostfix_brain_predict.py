#!/usr/bin/env python3
"""Prediction helper for GhostFix Brain v1."""

import argparse
import json
import pickle
import re
import sys
from pathlib import Path
from typing import Optional


DEFAULT_MODEL = Path("ml/models/ghostfix_brain_v1.pkl")

ERROR_TYPE_TEMPLATE_MAP = {
    "ModuleNotFoundError": "install_missing_module",
    "NameError": "define_or_correct_name",
    "FileNotFoundError": "verify_file_path",
    "KeyError": "check_key_or_get",
    "IndexError": "validate_index_bounds",
    "JSONDecodeError": "ensure_valid_json",
    "SyntaxError": "correct_syntax",
    "IndentationError": "correct_syntax",
    "TabError": "correct_syntax",
    "AttributeError": "check_attribute_or_type",
    "TypeError": "check_type_or_signature",
    "ValueError": "validate_value",
}


def build_input(error: str, message: str = "", context: str = "", failing_line: str = "") -> str:
    return "\n".join([
        f"ERROR: {error or ''}",
        f"MESSAGE: {message or ''}",
        f"CONTEXT: {context or ''}",
        f"FAILING_LINE: {failing_line or ''}",
    ]).strip()


def extract_error_type(text: str) -> str:
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b", text or "")
    return match.group(1) if match else ""


def normalize_decision_score(score: float) -> float:
    # Logistic-shaped normalization keeps unbounded margins in a 0-1 range.
    try:
        import math

        return 1.0 / (1.0 + math.exp(-float(score)))
    except OverflowError:
        return 1.0 if score > 0 else 0.0


def classifier_confidence(model, text: str, predicted_label: str) -> float:
    clf = model.named_steps.get("clf")
    if not hasattr(clf, "predict_proba"):
        if hasattr(model, "decision_function"):
            scores = model.decision_function([text])
            classes = list(model.classes_)
            try:
                class_index = classes.index(predicted_label)
            except ValueError:
                return 0.5
            raw_scores = scores[0] if hasattr(scores, "__len__") else scores
            if hasattr(raw_scores, "__len__"):
                return normalize_decision_score(float(raw_scores[class_index]))
            return normalize_decision_score(float(raw_scores))
        return 0.5
    probabilities = model.predict_proba([text])[0]
    classes = list(model.classes_)
    try:
        return float(probabilities[classes.index(predicted_label)])
    except ValueError:
        return 0.0


def has_traceback(error: str, message: str = "") -> bool:
    text = f"{error or ''}\n{message or ''}"
    return "Traceback (most recent call last)" in text or bool(re.search(r"\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception):", text))


def template_matches_error_type(error_type: str, fix_template: str) -> bool:
    return ERROR_TYPE_TEMPLATE_MAP.get(error_type) == fix_template


def apply_compatibility_guard(error_type: str, fix_template: str, confidence: float) -> tuple[str, float, bool, str]:
    allowed_template = ERROR_TYPE_TEMPLATE_MAP.get(error_type)
    if allowed_template and fix_template != allowed_template:
        return (
            allowed_template,
            max(0, confidence - 20),
            True,
            "incompatible_fix_template_corrected",
        )
    return fix_template, confidence, False, ""


def retriever_similarity(error: str, context: str) -> Optional[float]:
    try:
        from ml.predict_fix import predict_fix
    except ImportError:
        try:
            from predict_fix import predict_fix
        except ImportError:
            return None

    try:
        results = predict_fix(error, context=context, top_k=1)
    except Exception:
        return None
    if not results:
        return None
    return float(results[0].get("score", 0)) / 100.0


def load_model(model_path: Path = DEFAULT_MODEL) -> dict:
    with model_path.open("rb") as handle:
        return pickle.load(handle)


def predict(
    error: str,
    message: str = "",
    context: str = "",
    failing_line: str = "",
    model_path: Path = DEFAULT_MODEL,
    use_retriever: bool = True,
    artifact: Optional[dict] = None,
) -> dict:
    if artifact is None:
        artifact = load_model(model_path)
    text = build_input(error, message, context, failing_line)

    error_type_model = artifact["error_type_model"]
    fix_template_model = artifact["fix_template_model"]
    fix_templates = artifact.get("fix_templates", {})

    predicted_error_type = str(error_type_model.predict([text])[0])
    predicted_template = str(fix_template_model.predict([text])[0])

    error_prob = classifier_confidence(error_type_model, text, predicted_error_type)
    template_prob = classifier_confidence(fix_template_model, text, predicted_template)

    parsed_error_type = extract_error_type(f"{error}\n{message}")
    retriever_signal = retriever_similarity(error, context) if use_retriever else None

    confidence = ((0.65 * error_prob) + (0.35 * template_prob)) * 100

    if predicted_error_type and predicted_error_type in f"{error}\n{message}":
        confidence += 10
    elif parsed_error_type and parsed_error_type == predicted_error_type:
        confidence += 10

    if template_matches_error_type(predicted_error_type, predicted_template):
        confidence += 10

    if context or failing_line:
        confidence += 5

    if retriever_signal is not None:
        confidence += 5 * retriever_signal

    valid_prediction = bool(predicted_error_type and predicted_template)
    if valid_prediction and has_traceback(error, message) and (context or failing_line):
        confidence = max(confidence, 40)

    predicted_template, confidence, guard_applied, guard_reason = apply_compatibility_guard(
        predicted_error_type,
        predicted_template,
        confidence,
    )
    confidence = max(0, min(95, round(confidence, 2)))

    return {
        "error_type": predicted_error_type,
        "fix_template": predicted_template,
        "fix_template_text": fix_templates.get(predicted_template, predicted_template),
        "confidence": confidence,
        "source": "ghostfix_brain_v1",
        "guard_applied": guard_applied,
        "guard_reason": guard_reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Predict with GhostFix Brain v1")
    parser.add_argument("--error", default="", help="Traceback or exact error text")
    parser.add_argument("--message", default="")
    parser.add_argument("--context", default="")
    parser.add_argument("--failing-line", default="")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--no-retriever", action="store_true")
    args = parser.parse_args()

    error = args.error
    if not error and not sys.stdin.isatty():
        error = sys.stdin.read()

    result = predict(
        error=error,
        message=args.message,
        context=args.context,
        failing_line=args.failing_line,
        model_path=args.model,
        use_retriever=not args.no_retriever,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
