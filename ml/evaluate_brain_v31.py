#!/usr/bin/env python3
"""Evaluate GhostFix Brain v3.1 artifacts offline."""

from __future__ import annotations

import argparse
import json
import pickle
from collections import Counter
from pathlib import Path
from typing import Any

from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

try:
    from ml.evaluate_brain_v2_safety import ERROR_TYPE_TEMPLATE_MAP, load_jsonl
    from ml.ghostfix_brain_v2_predict import apply_auto_fix_safety_guard
    from ml.train_ghostfix_brain import build_input, fix_template
except ImportError:
    from evaluate_brain_v2_safety import ERROR_TYPE_TEMPLATE_MAP, load_jsonl
    from ghostfix_brain_v2_predict import apply_auto_fix_safety_guard
    from train_ghostfix_brain import build_input, fix_template


DEFAULT_MODEL = Path("ml/models/ghostfix_brain_v31.pkl")
DEFAULT_DATA = Path("ml/processed/ghostfix_real_world_eval_clean.jsonl")
FALLBACK_DATA = Path("ml/processed/ghostfix_real_world_eval.jsonl")
DEFAULT_REPORT = Path("ml/reports/ghostfix_brain_v31_realworld_eval.json")
TASKS = ("error_type", "fix_template", "complexity_class", "auto_fix_safety")
HIGH_CONFIDENCE_THRESHOLD = 0.85


def expected_labels(record: dict[str, Any]) -> dict[str, str]:
    return {
        "error_type": str(record.get("error_type") or ""),
        "fix_template": fix_template(record),
        "complexity_class": str(record.get("complexity_class") or "needs_context_reasoning"),
        "auto_fix_safety": "safe" if record.get("auto_fix_allowed_safe") else "not_safe",
    }


def compact(value: Any, limit: int = 600) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def ece(confidences: list[float], correct: list[bool], bins: int = 10) -> float:
    if not confidences:
        return 0.0
    total = len(confidences)
    score = 0.0
    for bucket in range(bins):
        low = bucket / bins
        high = (bucket + 1) / bins
        if bucket == bins - 1:
            indexes = [i for i, conf in enumerate(confidences) if low <= conf <= high]
        else:
            indexes = [i for i, conf in enumerate(confidences) if low <= conf < high]
        if not indexes:
            continue
        avg_conf = sum(confidences[i] for i in indexes) / len(indexes)
        avg_acc = sum(1 for i in indexes if correct[i]) / len(indexes)
        score += (len(indexes) / total) * abs(avg_conf - avg_acc)
    return round(score, 4)


def matrix_report(y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
    labels = sorted(set(y_true) | set(y_pred))
    return {"labels": labels, "matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist()}


def batch_predict(model: Any, texts: list[str]) -> tuple[list[str], list[float]]:
    predictions = [str(item) for item in model.predict(texts)]
    if not hasattr(model, "predict_proba"):
        return predictions, [0.5 for _ in predictions]
    classes = list(model.classes_)
    probabilities = model.predict_proba(texts)
    confidences = [
        float(row[classes.index(prediction)]) if prediction in classes else 0.0
        for row, prediction in zip(probabilities, predictions)
    ]
    return predictions, confidences


def resolve_data_path(path: Path) -> Path:
    if path.exists():
        return path
    if path == DEFAULT_DATA and FALLBACK_DATA.exists():
        return FALLBACK_DATA
    return path


def load_records_for_eval(data_path: Path, artifact: dict[str, Any], use_artifact_test_split: bool) -> tuple[list[dict[str, Any]], str]:
    if use_artifact_test_split:
        source_path = Path(str(artifact.get("data_path") or ""))
        records = load_jsonl(source_path)
        indexes = artifact.get("split", {}).get("test_idx", [])
        return [records[int(index)] for index in indexes], f"{source_path}::artifact_test_split"
    resolved = resolve_data_path(data_path)
    return load_jsonl(resolved), str(resolved)


def evaluate(
    model_path: Path,
    data_path: Path,
    report_path: Path,
    use_artifact_test_split: bool = False,
) -> dict[str, Any]:
    with model_path.open("rb") as handle:
        artifact = pickle.load(handle)

    records, data_label = load_records_for_eval(data_path, artifact, use_artifact_test_split)
    texts = [build_input(record) for record in records]
    expected = [expected_labels(record) for record in records]

    raw_predictions: dict[str, list[str]] = {}
    guarded_predictions: dict[str, list[str]] = {}
    confidences: dict[str, list[float]] = {}
    for task in TASKS:
        model = artifact["models"][task]
        raw_predictions[task], confidences[task] = batch_predict(model, texts)
        guarded_predictions[task] = list(raw_predictions[task])

    guard_cases: list[dict[str, Any]] = []
    for index, (record, text) in enumerate(zip(records, texts), start=1):
        raw_for_guard = {
            "error_type": raw_predictions["error_type"][index - 1],
            "fix_template": raw_predictions["fix_template"][index - 1],
            "complexity": raw_predictions["complexity_class"][index - 1],
            "auto_fix_safety": raw_predictions["auto_fix_safety"][index - 1],
        }
        confidence_for_guard = {
            "error_type": confidences["error_type"][index - 1],
            "fix_template": confidences["fix_template"][index - 1],
            "complexity": confidences["complexity_class"][index - 1],
            "auto_fix_safety": confidences["auto_fix_safety"][index - 1],
        }
        guarded_safety, reasons = apply_auto_fix_safety_guard(
            raw_for_guard,
            confidence_for_guard,
            text,
            str(record.get("failing_line") or ""),
        )
        guarded_predictions["auto_fix_safety"][index - 1] = guarded_safety
        if guarded_safety != raw_predictions["auto_fix_safety"][index - 1]:
            guard_cases.append({"record_index": index, "reasons": reasons})

    actual_by_task = {task: [labels[task] for labels in expected] for task in TASKS}
    high_conf_wrong: list[dict[str, Any]] = []
    unsafe_predicted_safe_before_guard: list[dict[str, Any]] = []
    guarded_unsafe_predicted_safe: list[dict[str, Any]] = []
    impossible_pairs: list[dict[str, Any]] = []

    for index, record in enumerate(records, start=1):
        for task in TASKS:
            actual = actual_by_task[task][index - 1]
            predicted = guarded_predictions[task][index - 1]
            confidence = confidences[task][index - 1]
            if actual != predicted and confidence >= HIGH_CONFIDENCE_THRESHOLD:
                high_conf_wrong.append(
                    {
                        "record_index": index,
                        "task": task,
                        "actual": actual,
                        "predicted": predicted,
                        "confidence": round(confidence, 4),
                        "message": compact(record.get("message") or record.get("error")),
                    }
                )

        if actual_by_task["auto_fix_safety"][index - 1] == "not_safe" and raw_predictions["auto_fix_safety"][index - 1] == "safe":
            unsafe_predicted_safe_before_guard.append(
                {
                    "record_index": index,
                    "confidence": round(confidences["auto_fix_safety"][index - 1], 4),
                    "guarded": guarded_predictions["auto_fix_safety"][index - 1],
                    "message": compact(record.get("message") or record.get("error")),
                }
            )
        if actual_by_task["auto_fix_safety"][index - 1] == "not_safe" and guarded_predictions["auto_fix_safety"][index - 1] == "safe":
            guarded_unsafe_predicted_safe.append(
                {
                    "record_index": index,
                    "confidence": round(confidences["auto_fix_safety"][index - 1], 4),
                    "message": compact(record.get("message") or record.get("error")),
                }
            )

        predicted_error = guarded_predictions["error_type"][index - 1]
        expected_template = ERROR_TYPE_TEMPLATE_MAP.get(predicted_error)
        predicted_template = guarded_predictions["fix_template"][index - 1]
        if expected_template and predicted_template != expected_template:
            impossible_pairs.append(
                {
                    "record_index": index,
                    "predicted_error_type": predicted_error,
                    "predicted_fix_template": predicted_template,
                    "expected_fix_template_for_error": expected_template,
                }
            )

    task_metrics: dict[str, Any] = {}
    for task in TASKS:
        guarded = guarded_predictions[task]
        actual = actual_by_task[task]
        correct = [a == p for a, p in zip(actual, guarded)]
        task_metrics[task] = {
            "accuracy": round(float(accuracy_score(actual, guarded)), 4) if actual else 0.0,
            "ece": ece(confidences[task], correct),
            "high_confidence_wrong_0_85": sum(
                1 for ok, conf in zip(correct, confidences[task])
                if not ok and conf >= HIGH_CONFIDENCE_THRESHOLD
            ),
            "classification_report": classification_report(actual, guarded, output_dict=True, zero_division=0),
            "confusion_matrix": matrix_report(actual, guarded),
            "actual_counts": dict(Counter(actual).most_common()),
        }

    mean_accuracy = round(sum(metric["accuracy"] for metric in task_metrics.values()) / len(TASKS), 4)
    mean_ece = round(sum(metric["ece"] for metric in task_metrics.values()) / len(TASKS), 4)
    report = {
        "version": artifact.get("version", "ghostfix_brain_v31"),
        "model": str(model_path),
        "data": data_label,
        "records": len(records),
        "mean_accuracy": mean_accuracy,
        "mean_ece": mean_ece,
        "task_metrics": task_metrics,
        "complexity_class_confusion_matrix": task_metrics["complexity_class"]["confusion_matrix"],
        "high_confidence_wrong_predictions": {
            "count": len(high_conf_wrong),
            "examples": high_conf_wrong[:100],
        },
        "unsafe_predicted_safe_before_guard": {
            "count": len(unsafe_predicted_safe_before_guard),
            "examples": unsafe_predicted_safe_before_guard[:100],
        },
        "guarded_unsafe_predicted_safe": {
            "count": len(guarded_unsafe_predicted_safe),
            "examples": guarded_unsafe_predicted_safe[:100],
        },
        "auto_fix_safety_guard": {
            "applied_count": len(guard_cases),
            "examples": guard_cases[:100],
        },
        "error_type_fix_template_impossible_pairs": {
            "count": len(impossible_pairs),
            "examples": impossible_pairs[:100],
        },
        "source_counts": dict(Counter(str(record.get("source") or "unknown") for record in records).most_common()),
        "note": "Evaluation only. Runtime and CLI are unchanged.",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate GhostFix Brain v3.1 offline.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--test-split", action="store_true", help="Evaluate the artifact's saved test split.")
    args = parser.parse_args()

    report = evaluate(args.model, args.data, args.report, use_artifact_test_split=args.test_split)
    print(f"Records: {report['records']}")
    print(f"Mean accuracy: {report['mean_accuracy']}")
    print(f"Mean ECE: {report['mean_ece']}")
    print(f"High-confidence wrong: {report['high_confidence_wrong_predictions']['count']}")
    print(f"Unsafe predicted safe before guard: {report['unsafe_predicted_safe_before_guard']['count']}")
    print(f"Guarded unsafe predicted safe: {report['guarded_unsafe_predicted_safe']['count']}")
    print("Complexity class confusion matrix:")
    print(json.dumps(report["complexity_class_confusion_matrix"], indent=2, ensure_ascii=False))
    print(f"Report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
