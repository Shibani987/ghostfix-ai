#!/usr/bin/env python3
"""Evaluate GhostFix Brain v2 safety without changing runtime behavior."""

from __future__ import annotations

import argparse
import json
import pickle
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from ml.train_ghostfix_brain import build_input, fix_template
    from ml.ghostfix_brain_v2_predict import predict_record
except ImportError:
    from train_ghostfix_brain import build_input, fix_template
    from ghostfix_brain_v2_predict import predict_record


DEFAULT_MODEL = Path("ml/models/ghostfix_brain_v2.pkl")
DEFAULT_DATA = Path("ml/processed/ghostfix_real_debug_dataset_v2_3000_clean.jsonl")
DEFAULT_REPORT = Path("ml/reports/brain_v2_safety_report.json")

HIGH_CONFIDENCE_THRESHOLD = 0.85
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


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSONL record: {exc}") from exc
    return records


def load_model(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        artifact = pickle.load(handle)
    if "models" not in artifact:
        raise ValueError(f"{path} is not a GhostFix Brain v2 artifact: missing 'models'")
    return artifact


def snippet(value: Any, limit: int = 500) -> str:
    text = str(value or "").strip()
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def confusion_counts(actual: list[str], predicted: list[str], limit: int = 25) -> list[dict[str, Any]]:
    counts = Counter()
    for actual_label, predicted_label in zip(actual, predicted):
        if actual_label != predicted_label:
            counts[(actual_label, predicted_label)] += 1
    return [
        {"actual": actual_label, "predicted": predicted_label, "count": count}
        for (actual_label, predicted_label), count in counts.most_common(limit)
    ]


def accuracy(actual: list[str], predicted: list[str]) -> float:
    if not actual:
        return 0.0
    return round(sum(1 for a, p in zip(actual, predicted) if a == p) / len(actual), 4)


def case_record(
    index: int,
    record: dict[str, Any],
    predictions: dict[str, str],
    confidences: dict[str, float],
    reasons: list[str],
    risk_score: float | None = None,
) -> dict[str, Any]:
    result = {
        "record_index": index,
        "reasons": reasons,
        "actual": {
            "error_type": record.get("error_type"),
            "fix_template": fix_template(record),
            "complexity": record.get("complexity_class"),
            "auto_fix_safety": "safe" if record.get("auto_fix_allowed_safe") else "not_safe",
        },
        "predicted": predictions,
        "confidence": confidences,
        "source": record.get("source", ""),
        "message": snippet(record.get("message") or record.get("error"), 700),
        "context": snippet(record.get("context"), 500),
        "failing_line": snippet(record.get("failing_line"), 250),
        "fix": snippet(record.get("fix"), 500),
    }
    if risk_score is not None:
        result["risk_score"] = round(risk_score, 4)
    return result


def evaluate(model_path: Path, data_path: Path, report_path: Path) -> dict[str, Any]:
    artifact = load_model(model_path)
    models = artifact["models"]
    records = load_jsonl(data_path)

    required_heads = {"error_type", "fix_template", "complexity", "auto_fix_safety"}
    missing_heads = sorted(required_heads - set(models))
    if missing_heads:
        raise ValueError(f"{model_path} is missing Brain v2 heads: {missing_heads}")

    actual_by_task: dict[str, list[str]] = {task: [] for task in required_heads}
    raw_predicted_by_task: dict[str, list[str]] = {task: [] for task in required_heads}
    guarded_predicted_by_task: dict[str, list[str]] = {task: [] for task in required_heads}
    high_confidence_wrong: list[dict[str, Any]] = []
    raw_unsafe_predicted_safe: list[dict[str, Any]] = []
    guarded_unsafe_predicted_safe: list[dict[str, Any]] = []
    impossible_mappings: list[dict[str, Any]] = []
    complexity_confusion_cases: list[dict[str, Any]] = []
    scored_cases: list[dict[str, Any]] = []
    guard_applied_cases: list[dict[str, Any]] = []

    for index, record in enumerate(records, start=1):
        actual = {
            "error_type": str(record.get("error_type") or ""),
            "fix_template": fix_template(record),
            "complexity": str(record.get("complexity_class") or "needs_context_reasoning"),
            "auto_fix_safety": "safe" if record.get("auto_fix_allowed_safe") else "not_safe",
        }
        prediction_result = predict_record(record, model_path, artifact=artifact)
        raw_predictions = prediction_result["raw_prediction"]
        predictions = prediction_result["guarded_prediction"]
        confidences = prediction_result["confidence"]

        for task in sorted(required_heads):
            actual_by_task[task].append(actual[task])
            raw_predicted_by_task[task].append(raw_predictions[task])
            guarded_predicted_by_task[task].append(predictions[task])

        reasons: list[str] = []
        risk_score = 0.0

        if prediction_result["auto_fix_safety_guard_applied"]:
            guard_applied_cases.append(
                case_record(
                    index,
                    record,
                    raw_predictions,
                    confidences,
                    prediction_result["auto_fix_safety_guard_reasons"],
                )
            )

        for task in sorted(required_heads):
            if predictions[task] != actual[task]:
                if confidences[task] >= HIGH_CONFIDENCE_THRESHOLD:
                    reasons.append(f"high_confidence_wrong_{task}")
                    high_confidence_wrong.append(
                        case_record(index, record, predictions, confidences, [f"wrong_{task}"])
                    )
                risk_score += confidences[task]

        if actual["auto_fix_safety"] == "not_safe" and raw_predictions["auto_fix_safety"] == "safe":
            raw_unsafe_predicted_safe.append(
                case_record(index, record, raw_predictions, confidences, ["raw_unsafe_auto_fix_safety_predicted_safe"])
            )

        if actual["auto_fix_safety"] == "not_safe" and predictions["auto_fix_safety"] == "safe":
            reasons.append("guarded_unsafe_auto_fix_safety_predicted_safe")
            risk_score += 3.0 + confidences["auto_fix_safety"]
            guarded_unsafe_predicted_safe.append(
                case_record(index, record, predictions, confidences, ["guarded_unsafe_auto_fix_safety_predicted_safe"])
            )

        expected_template = ERROR_TYPE_TEMPLATE_MAP.get(predictions["error_type"])
        if expected_template and predictions["fix_template"] != expected_template:
            reasons.append("impossible_error_type_fix_template_mapping")
            risk_score += 2.0 + confidences["fix_template"]
            impossible_mappings.append(
                case_record(
                    index,
                    record,
                    predictions,
                    confidences,
                    ["impossible_error_type_fix_template_mapping"],
                )
            )

        if predictions["complexity"] != actual["complexity"]:
            reasons.append("complexity_confusion")
            risk_score += 1.0 + confidences["complexity"]
            complexity_confusion_cases.append(
                case_record(index, record, predictions, confidences, ["complexity_confusion"])
            )

        if reasons:
            scored_cases.append(case_record(index, record, predictions, confidences, reasons, risk_score))

    worst_30 = sorted(scored_cases, key=lambda item: item["risk_score"], reverse=True)[:30]
    task_metrics = {
        task: {
            "raw_accuracy": accuracy(actual_by_task[task], raw_predicted_by_task[task]),
            "guarded_accuracy": accuracy(actual_by_task[task], guarded_predicted_by_task[task]),
            "actual_counts": dict(Counter(actual_by_task[task]).most_common()),
            "raw_predicted_counts": dict(Counter(raw_predicted_by_task[task]).most_common()),
            "guarded_predicted_counts": dict(Counter(guarded_predicted_by_task[task]).most_common()),
            "raw_confusion": confusion_counts(actual_by_task[task], raw_predicted_by_task[task]),
            "guarded_confusion": confusion_counts(actual_by_task[task], guarded_predicted_by_task[task]),
        }
        for task in sorted(required_heads)
    }

    report = {
        "model": str(model_path),
        "data": str(data_path),
        "records_evaluated": len(records),
        "high_confidence_threshold": HIGH_CONFIDENCE_THRESHOLD,
        "task_metrics": task_metrics,
        "auto_fix_safety_guard": {
            "rules": [
                "force not_safe when predicted complexity is needs_project_context",
                "force not_safe when predicted complexity is unsafe_to_autofix",
                "force not_safe when predicted error_type is FileNotFoundError, PermissionError, or RuntimeError",
                "force not_safe when auto_fix_safety confidence is below 0.95",
                "allow safe only for deterministic_safe empty-json JSONDecodeError or missing-colon SyntaxError patterns",
            ],
            "applied_count": len(guard_applied_cases),
            "examples": guard_applied_cases[:100],
        },
        "high_confidence_wrong_predictions": {
            "count": len(high_confidence_wrong),
            "examples": high_confidence_wrong[:100],
        },
        "raw_unsafe_auto_fix_safety_predicted_safe": {
            "count": len(raw_unsafe_predicted_safe),
            "examples": raw_unsafe_predicted_safe[:100],
        },
        "guarded_unsafe_auto_fix_safety_predicted_safe": {
            "count": len(guarded_unsafe_predicted_safe),
            "examples": guarded_unsafe_predicted_safe[:100],
        },
        "impossible_error_type_fix_template_mapping": {
            "count": len(impossible_mappings),
            "examples": impossible_mappings[:100],
        },
        "complexity_confusion": {
            "count": len(complexity_confusion_cases),
            "top_confusions": task_metrics["complexity"]["guarded_confusion"],
            "examples": complexity_confusion_cases[:100],
        },
        "worst_30_predictions": worst_30,
        "safety_passed": (
            not guarded_unsafe_predicted_safe
            and not impossible_mappings
        ),
        "model_quality_passed": not high_confidence_wrong and not complexity_confusion_cases,
        "note": "Evaluation only. Runtime was not updated.",
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate GhostFix Brain v2 safety. Does not update runtime.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    report = evaluate(args.model, args.data, args.report)
    print(f"Records evaluated: {report['records_evaluated']}")
    print(f"High confidence wrong predictions: {report['high_confidence_wrong_predictions']['count']}")
    print(f"Raw unsafe auto_fix_safety predicted safe: {report['raw_unsafe_auto_fix_safety_predicted_safe']['count']}")
    print(f"Guarded unsafe auto_fix_safety predicted safe: {report['guarded_unsafe_auto_fix_safety_predicted_safe']['count']}")
    print(f"Impossible error_type/fix_template mappings: {report['impossible_error_type_fix_template_mapping']['count']}")
    print(f"Complexity confusion count: {report['complexity_confusion']['count']}")
    print("Task accuracy:")
    for task, metrics in report["task_metrics"].items():
        print(f"  {task}: raw={metrics['raw_accuracy']} guarded={metrics['guarded_accuracy']}")
    print(f"Safety passed: {str(report['safety_passed']).lower()}")
    print(f"Report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
