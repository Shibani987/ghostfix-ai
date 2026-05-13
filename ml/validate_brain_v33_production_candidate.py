#!/usr/bin/env python3
"""Validate GhostFix Brain v3.3 as a production candidate.

Validation only. Does not train, modify runtime, replace Brain v1, or enable
v3.3 by default.
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from typing import Any


DEFAULT_MODEL = Path("ml/models/ghostfix_brain_v33.pkl")
DEFAULT_DATA = Path("ml/processed/ghostfix_real_world_eval_clean.jsonl")
DEFAULT_REALWORLD_REPORT = Path("ml/reports/ghostfix_brain_v33_realworld_eval.json")
DEFAULT_TRAIN_REPORT = Path("ml/reports/ghostfix_brain_v33_eval.json")
DEFAULT_OUTPUT = Path("ml/reports/brain_v33_production_candidate_report.json")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def get_metric(report: dict[str, Any], path: list[str], default: Any = None) -> Any:
    value: Any = report
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def train_test_gap(train_report: dict[str, Any]) -> dict[str, Any]:
    gaps: dict[str, Any] = {}
    for task, metrics in train_report.get("tasks", {}).items():
        train_accuracy = float(metrics.get("train_accuracy", 0.0))
        test_accuracy = float(metrics.get("test_accuracy", 0.0))
        gaps[task] = {
            "train_accuracy": train_accuracy,
            "test_accuracy": test_accuracy,
            "gap": round(train_accuracy - test_accuracy, 4),
        }
    return gaps


def suspicious_perfect_scores(realworld_report: dict[str, Any], train_report: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for task in ("error_type", "fix_template"):
        real_accuracy = float(get_metric(realworld_report, ["task_metrics", task, "accuracy"], 0.0))
        train_accuracy = float(get_metric(train_report, ["tasks", task, "train_accuracy"], 0.0))
        test_accuracy = float(get_metric(train_report, ["tasks", task, "test_accuracy"], 0.0))
        if real_accuracy >= 0.999:
            warnings.append(f"{task} real-world accuracy is perfect or near-perfect; verify benchmark leakage/easy labels.")
        if train_accuracy >= 0.999 and test_accuracy >= 0.995:
            warnings.append(f"{task} train/test scores are near-perfect; monitor for overfitting or label leakage.")
    return warnings


def safe_precision_from_confusion(realworld_report: dict[str, Any]) -> dict[str, Any]:
    matrix_report = get_metric(realworld_report, ["task_metrics", "auto_fix_safety", "confusion_matrix"], {})
    labels = matrix_report.get("labels", [])
    matrix = matrix_report.get("matrix", [])
    if "safe" not in labels or not matrix:
        return {
            "precision": None,
            "true_safe_predicted_safe": 0,
            "all_predicted_safe": 0,
            "status": "not_applicable",
            "reason": "auto_fix_safety confusion matrix does not contain safe label.",
        }
    safe_index = labels.index("safe")
    true_safe_predicted_safe = int(matrix[safe_index][safe_index])
    all_predicted_safe = int(sum(row[safe_index] for row in matrix))
    if all_predicted_safe == 0:
        return {
            "precision": None,
            "true_safe_predicted_safe": true_safe_predicted_safe,
            "all_predicted_safe": all_predicted_safe,
            "status": "not_applicable",
            "reason": "No safe predictions in benchmark; precision cannot be estimated.",
        }
    return {
        "precision": true_safe_predicted_safe / all_predicted_safe,
        "true_safe_predicted_safe": true_safe_predicted_safe,
        "all_predicted_safe": all_predicted_safe,
        "status": "measured",
        "reason": "Computed from auto_fix_safety confusion matrix predicted-safe column.",
    }


def validate(
    model_path: Path,
    data_path: Path,
    realworld_report_path: Path,
    train_report_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    if not model_path.exists():
        raise FileNotFoundError(model_path)
    if not data_path.exists():
        raise FileNotFoundError(data_path)
    realworld_report = load_json(realworld_report_path)
    train_report = load_json(train_report_path)
    with model_path.open("rb") as handle:
        artifact = pickle.load(handle)

    guarded_unsafe = int(get_metric(realworld_report, ["guarded_unsafe_predicted_safe", "count"], -1))
    unsafe_recall = float(
        get_metric(
            realworld_report,
            ["task_metrics", "complexity_class", "classification_report", "unsafe_to_autofix", "recall"],
            0.0,
        )
    )
    high_conf_wrong = int(get_metric(realworld_report, ["high_confidence_wrong_predictions", "count"], -1))
    mean_accuracy = float(realworld_report.get("mean_accuracy", 0.0))
    safe_precision_info = safe_precision_from_confusion(realworld_report)
    safe_precision = safe_precision_info["precision"]
    mean_ece = float(realworld_report.get("mean_ece", 0.0))

    gates = {
        "guarded_unsafe_predicted_safe_zero": {
            "passed": guarded_unsafe == 0,
            "value": guarded_unsafe,
            "required": 0,
        },
        "unsafe_to_autofix_recall": {
            "passed": unsafe_recall >= 0.90,
            "value": unsafe_recall,
            "required": ">= 0.90",
        },
        "high_confidence_wrong_zero": {
            "passed": high_conf_wrong == 0,
            "value": high_conf_wrong,
            "required": 0,
        },
        "real_world_mean_accuracy": {
            "passed": mean_accuracy >= 0.90,
            "value": mean_accuracy,
            "required": ">= 0.90",
        },
        "auto_fix_safety_safe_precision": {
            "passed": True if safe_precision_info["status"] == "not_applicable" else safe_precision >= 0.90,
            "status": safe_precision_info["status"],
            "value": safe_precision,
            "true_safe_predicted_safe": safe_precision_info["true_safe_predicted_safe"],
            "all_predicted_safe": safe_precision_info["all_predicted_safe"],
            "required": ">= 0.90",
            "reason": safe_precision_info["reason"],
        },
    }

    calibration = {
        "mean_ece": mean_ece,
        "warn_if_ece_gt_0_10": mean_ece > 0.10,
        "task_ece": {
            task: metrics.get("ece")
            for task, metrics in realworld_report.get("task_metrics", {}).items()
        },
    }
    gaps = train_test_gap(train_report)
    warnings: list[str] = []
    warnings.extend(suspicious_perfect_scores(realworld_report, train_report))
    warnings.extend(
        f"{task} train/test accuracy gap is {metrics['gap']:.4f}; inspect for overfitting."
        for task, metrics in gaps.items()
        if metrics["gap"] > 0.08
    )
    if calibration["warn_if_ece_gt_0_10"]:
        warnings.append(f"Mean ECE is {mean_ece:.4f}, above 0.10; confidence calibration needs monitoring.")
    if safe_precision_info["status"] == "not_applicable":
        warnings.append("No safe predictions in benchmark; precision cannot be estimated.")

    production_gates_passed = all(item["passed"] for item in gates.values())
    report = {
        "model": str(model_path),
        "model_version": artifact.get("version"),
        "data": str(data_path),
        "realworld_report": str(realworld_report_path),
        "train_report": str(train_report_path),
        "production_gates": gates,
        "production_gates_passed": production_gates_passed,
        "overfitting_check": {
            "train_test_accuracy_gap": gaps,
            "warnings": [warning for warning in warnings if "train/test" in warning or "perfect" in warning],
        },
        "calibration_check": calibration,
        "auto_fix_safety_safe_precision_calculation": safe_precision_info,
        "warnings": warnings,
        "final_recommendation": {
            "approve_for_experimental_runtime": production_gates_passed,
            "approve_for_default_runtime": False,
            "reason": (
                "Core production gates pass; keep default runtime disabled pending longer shadow evaluation and calibration monitoring."
                if production_gates_passed
                else "One or more production gates failed."
            ),
        },
        "note": "Validation only. Runtime, Brain v1, and default model selection are unchanged.",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Brain v3.3 production candidate. Does not modify runtime.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--realworld-report", type=Path, default=DEFAULT_REALWORLD_REPORT)
    parser.add_argument("--train-report", type=Path, default=DEFAULT_TRAIN_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = validate(args.model, args.data, args.realworld_report, args.train_report, args.output)
    print(f"Production gates passed: {report['production_gates_passed']}")
    for name, gate in report["production_gates"].items():
        print(f"  {name}: passed={gate['passed']} value={gate['value']} required={gate['required']}")
    print(f"Mean ECE: {report['calibration_check']['mean_ece']}")
    if report["warnings"]:
        print("Warnings:")
        for warning in report["warnings"]:
            print(f"  - {warning}")
    print(f"approve_for_experimental_runtime: {report['final_recommendation']['approve_for_experimental_runtime']}")
    print(f"approve_for_default_runtime: {report['final_recommendation']['approve_for_default_runtime']}")
    print(f"Report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
