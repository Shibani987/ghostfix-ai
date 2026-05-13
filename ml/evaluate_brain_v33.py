#!/usr/bin/env python3
"""Evaluate GhostFix Brain v3.3 offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from ml.evaluate_brain_v31 import evaluate
except ImportError:
    from evaluate_brain_v31 import evaluate


DEFAULT_MODEL = Path("ml/models/ghostfix_brain_v33.pkl")
DEFAULT_DATA = Path("ml/processed/ghostfix_real_world_eval_clean.jsonl")
DEFAULT_REPORT = Path("ml/reports/ghostfix_brain_v33_realworld_eval.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate GhostFix Brain v3.3 offline.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--test-split", action="store_true")
    args = parser.parse_args()
    report = evaluate(args.model, args.data, args.report, use_artifact_test_split=args.test_split)
    unsafe_recall = (
        report["task_metrics"]
        .get("complexity_class", {})
        .get("classification_report", {})
        .get("unsafe_to_autofix", {})
        .get("recall", 0.0)
    )
    print(f"Records: {report['records']}")
    print(f"Mean accuracy: {report['mean_accuracy']}")
    print(f"Mean ECE: {report['mean_ece']}")
    print(f"High-confidence wrong: {report['high_confidence_wrong_predictions']['count']}")
    print(f"Unsafe predicted safe before guard: {report['unsafe_predicted_safe_before_guard']['count']}")
    print(f"Guarded unsafe predicted safe: {report['guarded_unsafe_predicted_safe']['count']}")
    print("Complexity class confusion matrix:")
    print(json.dumps(report["complexity_class_confusion_matrix"], indent=2, ensure_ascii=False))
    print(f"unsafe_to_autofix recall: {unsafe_recall}")
    print(f"Report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
