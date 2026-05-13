#!/usr/bin/env python3
"""Run GhostFix Brain v3.3 in offline shadow mode beside Brain v1.

This script does not modify runtime decisions. Brain v1 is always treated as
the used prediction; Brain v3.3 is logged as shadow-only metadata.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from ml.ghostfix_brain_predict import load_model as load_v1_model
    from ml.ghostfix_brain_predict import predict as predict_v1
    from ml.ghostfix_brain_v33_predict import load_model as load_v33_model
    from ml.ghostfix_brain_v33_predict import predict_record as predict_v33_record
except ImportError:
    from ghostfix_brain_predict import load_model as load_v1_model
    from ghostfix_brain_predict import predict as predict_v1
    from ghostfix_brain_v33_predict import load_model as load_v33_model
    from ghostfix_brain_v33_predict import predict_record as predict_v33_record


DEFAULT_INPUT = Path("ml/processed/ghostfix_real_world_eval_clean.jsonl")
FALLBACK_INPUT = Path("ml/processed/ghostfix_dataset_v3_strict.jsonl")
DEFAULT_LOG = Path("ml/reports/shadow_mode_log.jsonl")
SHADOW_FLAG = "GHOSTFIX_SHADOW_V33"
TASKS = ("error_type", "fix_template", "complexity_class", "auto_fix_safety")
V1_COMPARABLE_TASKS = ("error_type", "fix_template")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} is not valid JSONL: {exc}") from exc
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def dataset_path(default_path: Path = DEFAULT_INPUT) -> Path:
    if default_path.exists():
        return default_path
    return FALLBACK_INPUT


def expected_values(record: dict[str, Any]) -> dict[str, str]:
    return {
        "error_type": str(record.get("error_type") or ""),
        "fix_template": str(record.get("fix_template") or ""),
        "complexity_class": str(record.get("complexity_class") or ""),
        "auto_fix_safety": "safe" if record.get("auto_fix_allowed_safe") is True else "not_safe",
    }


def normalize_v1(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "error_type": str(result.get("error_type") or ""),
        "fix_template": str(result.get("fix_template") or ""),
        "complexity_class": "",
        "auto_fix_safety": "",
        "confidence": float(result.get("confidence") or 0.0),
    }


def normalize_v33(result: dict[str, Any]) -> dict[str, Any]:
    guarded = result.get("guarded_prediction") or {}
    confidences = result.get("confidence") or {}
    confidence_values = [float(value) for value in confidences.values()] or [0.0]
    return {
        "error_type": str(guarded.get("error_type") or ""),
        "fix_template": str(guarded.get("fix_template") or ""),
        "complexity_class": str(guarded.get("complexity_class") or ""),
        "auto_fix_safety": str(guarded.get("auto_fix_safety") or ""),
        "confidence": round(max(confidence_values) * 100, 2),
    }


def prediction_matches(prediction: dict[str, Any], expected: dict[str, str], task: str) -> bool | None:
    expected_value = expected.get(task, "")
    if not expected_value:
        return None
    predicted_value = str(prediction.get(task) or "")
    if not predicted_value:
        return False
    return predicted_value == expected_value


def compare_case(index: int, record: dict[str, Any], v1: dict[str, Any], v33: dict[str, Any]) -> dict[str, Any]:
    expected = expected_values(record)
    disagreements = {task: v1.get(task) != v33.get(task) for task in TASKS}
    v33_better_tasks: list[str] = []
    v33_worse_tasks: list[str] = []
    for task in TASKS:
        v1_match = prediction_matches(v1, expected, task)
        v33_match = prediction_matches(v33, expected, task)
        if v1_match is False and v33_match is True:
            v33_better_tasks.append(task)
        elif v1_match is True and v33_match is False:
            v33_worse_tasks.append(task)

    return {
        "index": index,
        "source": record.get("source") or "",
        "expected": expected,
        "v1": v1,
        "v33_shadow": v33,
        "disagreement": any(disagreements.values()),
        "disagreement_flags": disagreements,
        "v33_better_tasks": v33_better_tasks,
        "v33_worse_tasks": v33_worse_tasks,
        "message_snippet": str(record.get("message") or record.get("error") or "")[:300],
        "context_snippet": str(record.get("context") or "")[:300],
    }


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(cases)
    disagreement_count = sum(1 for case in cases if case["disagreement"])
    comparable_disagreement_count = sum(
        1
        for case in cases
        if any(case["disagreement_flags"].get(task) for task in V1_COMPARABLE_TASKS)
    )
    disagreement_by_task = Counter()
    better_by_task = Counter()
    worse_by_task = Counter()
    comparable_better_cases = 0
    comparable_worse_cases = 0
    better_cases = 0
    worse_cases = 0
    for case in cases:
        for task, disagreed in case["disagreement_flags"].items():
            if disagreed:
                disagreement_by_task[task] += 1
        for task in case["v33_better_tasks"]:
            better_by_task[task] += 1
        for task in case["v33_worse_tasks"]:
            worse_by_task[task] += 1
        better_cases += bool(case["v33_better_tasks"])
        worse_cases += bool(case["v33_worse_tasks"])
        comparable_better_cases += any(task in V1_COMPARABLE_TASKS for task in case["v33_better_tasks"])
        comparable_worse_cases += any(task in V1_COMPARABLE_TASKS for task in case["v33_worse_tasks"])

    return {
        "records": total,
        "disagreements": disagreement_count,
        "disagreement_rate": round(disagreement_count / total, 4) if total else 0.0,
        "comparable_disagreements": comparable_disagreement_count,
        "comparable_disagreement_rate": round(comparable_disagreement_count / total, 4) if total else 0.0,
        "disagreement_by_task": dict(disagreement_by_task),
        "v33_better_cases": better_cases,
        "v33_worse_cases": worse_cases,
        "v33_better_cases_on_v1_heads": comparable_better_cases,
        "v33_worse_cases_on_v1_heads": comparable_worse_cases,
        "v33_better_by_task": dict(better_by_task),
        "v33_worse_by_task": dict(worse_by_task),
        "log_path": str(DEFAULT_LOG),
    }


def run_shadow_mode(input_path: Path, log_path: Path) -> dict[str, Any]:
    records = load_jsonl(input_path)
    v1_artifact = load_v1_model()
    v33_artifact = load_v33_model()
    cases: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        v1_result = predict_v1(
            error=str(record.get("error") or ""),
            message=str(record.get("message") or ""),
            context=str(record.get("context") or ""),
            failing_line=str(record.get("failing_line") or ""),
            use_retriever=False,
            artifact=v1_artifact,
        )
        v33_result = predict_v33_record(record, artifact=v33_artifact)
        cases.append(compare_case(index, record, normalize_v1(v1_result), normalize_v33(v33_result)))

    write_jsonl(log_path, cases)
    summary = summarize(cases)
    summary["input_path"] = str(input_path)
    summary["log_path"] = str(log_path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run GhostFix Brain v3.3 shadow mode without changing runtime decisions.")
    parser.add_argument("--input", type=Path, default=dataset_path())
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--force", action="store_true", help=f"Run even when {SHADOW_FLAG}=1 is not set.")
    args = parser.parse_args()

    if os.getenv(SHADOW_FLAG) != "1" and not args.force:
        print(f"Shadow mode disabled. Set {SHADOW_FLAG}=1 to run Brain v3.3 in shadow mode.")
        return 0

    summary = run_shadow_mode(args.input, args.log)
    print(f"Records: {summary['records']}")
    print(f"Disagreement rate (all logged fields): {summary['disagreement_rate']:.2%}")
    print(f"Disagreement rate (v1-comparable heads): {summary['comparable_disagreement_rate']:.2%}")
    print(f"Disagreements: {summary['disagreements']}")
    print(f"Comparable disagreements: {summary['comparable_disagreements']}")
    print(f"v3.3 better than v1 (all labeled heads): {summary['v33_better_cases']}")
    print(f"v3.3 worse than v1 (all labeled heads): {summary['v33_worse_cases']}")
    print(f"v3.3 better than v1 (v1 heads only): {summary['v33_better_cases_on_v1_heads']}")
    print(f"v3.3 worse than v1 (v1 heads only): {summary['v33_worse_cases_on_v1_heads']}")
    print("Disagreement by task:")
    for task, count in sorted(summary["disagreement_by_task"].items()):
        print(f"  {task}: {count}")
    print("v3.3 better by task:")
    for task, count in sorted(summary["v33_better_by_task"].items()):
        print(f"  {task}: {count}")
    print("v3.3 worse by task:")
    for task, count in sorted(summary["v33_worse_by_task"].items()):
        print(f"  {task}: {count}")
    print(f"Shadow log: {summary['log_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
