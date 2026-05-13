from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.brain_v4_inference import (
    BrainV4Inference,
    DEFAULT_CONFIG,
    finalize_brain_v4_output,
    has_exact_brain_v4_schema,
    load_config,
    parse_brain_v4_output,
)


JSON_REPORT = Path("ml/reports/brain_v4_eval_report.json")
MD_REPORT = Path("ml/reports/brain_v4_eval_report.md")
MALFORMED_REPORT = Path("ml/reports/malformed_outputs.jsonl")
SCHEMA_MISMATCH_REPORT = Path("ml/reports/schema_mismatches.jsonl")
DEBUG_GENERATIONS_REPORT = Path("ml/reports/brain_v4_debug_generations.jsonl")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate GhostFix Brain v4 LoRA adapter locally.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to Brain v4 LoRA YAML config.")
    parser.add_argument("--limit", type=int, default=0, help="Optional validation record limit.")
    args = parser.parse_args()

    report = evaluate(config_path=args.config, limit=args.limit or None)
    write_reports(report)
    if report["status"] == "unavailable":
        print(f"Brain v4 evaluation unavailable: {report['reason']}")
        print(f"Wrote {JSON_REPORT}")
        print(f"Wrote {MD_REPORT}")
        return 0
    print(f"Brain v4 evaluation complete: valid_json_rate={report['metrics']['valid_json_rate']:.2f}")
    print(f"Wrote {JSON_REPORT}")
    print(f"Wrote {MD_REPORT}")
    print(f"Wrote {MALFORMED_REPORT}")
    print(f"Wrote {SCHEMA_MISMATCH_REPORT}")
    print(f"Wrote {DEBUG_GENERATIONS_REPORT}")
    return 0


def evaluate(config_path: str | Path = DEFAULT_CONFIG, limit: int | None = None) -> dict[str, Any]:
    config = load_config(config_path)
    val_file = Path(str((config.get("data") or {}).get("val_file") or "ml/processed/brain_v4_lora_val.jsonl"))
    records = _read_jsonl(val_file)
    if limit:
        records = records[:limit]
    runner = BrainV4Inference(config_path)
    status = runner.load()
    if not status.available:
        return {
            "status": "unavailable",
            "reason": status.reason,
            "validation_file": str(val_file),
            "record_count": len(records),
            "metrics": empty_metrics(),
            "samples": [],
            "malformed_outputs": [],
            "schema_mismatches": [],
            "debug_generations": [],
        }

    predictions = []
    debug_generations = []
    for index, record in enumerate(records):
        expected = _expected_output(record)
        result = runner.diagnose(
            terminal_error=record.get("input", ""),
            context=record.get("input", ""),
            language=expected.get("language", "unknown"),
            framework=expected.get("framework", "unknown"),
            include_debug=index < 10,
        )
        prediction = result.get("diagnosis") if result.get("available") else None
        predictions.append(prediction)
        if index < 10:
            debug_generations.append({
                "index": index,
                "input": record.get("input", ""),
                "expected_output": expected,
                "raw_model_output": result.get("raw_output", ""),
                "parsed_raw_json": result.get("parsed_output"),
                "final_normalized_output": prediction,
            })
        if index < 3:
            print(f"Brain v4 debug sample {index + 1} final output:")
            print(prediction)
    metrics = evaluate_predictions(records, predictions)
    return {
        "status": "ok",
        "reason": "",
        "validation_file": str(val_file),
        "record_count": len(records),
        "metrics": metrics,
        "samples": _sample_rows(records, predictions),
        "malformed_outputs": _malformed_rows(records, predictions),
        "schema_mismatches": _schema_mismatch_rows(records, predictions),
        "debug_generations": debug_generations,
    }


def evaluate_predictions(
    records: list[dict[str, Any]],
    predictions: list[dict[str, Any] | tuple[Any, ...] | str | None],
) -> dict[str, Any]:
    total = len(records)
    valid = 0
    malformed = 0
    error_type_correct = 0
    root_cause_correct = 0
    safe_correct = 0
    confidence_sum = 0
    exact_schema = 0

    for record, prediction_value in zip(records, predictions):
        prediction = _normalize_prediction(prediction_value)
        expected = _expected_output(record)
        if not prediction:
            malformed += 1
            continue
        valid += 1
        if _prediction_schema_exact(prediction_value):
            exact_schema += 1
        if prediction.get("error_type") == expected.get("error_type"):
            error_type_correct += 1
        if prediction.get("root_cause") == expected.get("root_cause"):
            root_cause_correct += 1
        if bool(prediction.get("safe_to_autofix")) == bool(expected.get("safe_to_autofix")):
            safe_correct += 1
        try:
            confidence_sum += int(prediction.get("confidence", 0))
        except (TypeError, ValueError):
            pass

    denominator = max(total, 1)
    valid_denominator = max(valid, 1)
    return {
        "valid_json_rate": valid / denominator,
        "error_type_accuracy": error_type_correct / denominator,
        "root_cause_accuracy": root_cause_correct / denominator,
        "safe_to_autofix_accuracy": safe_correct / denominator,
        "average_confidence": confidence_sum / valid_denominator if valid else 0.0,
        "malformed_output_count": malformed,
        "exact_schema_match": exact_schema / denominator,
        "schema_mismatch_count": valid - exact_schema,
    }


def empty_metrics() -> dict[str, Any]:
    return {
        "valid_json_rate": 0.0,
        "error_type_accuracy": 0.0,
        "root_cause_accuracy": 0.0,
        "safe_to_autofix_accuracy": 0.0,
        "average_confidence": 0.0,
        "malformed_output_count": 0,
        "exact_schema_match": 0.0,
        "schema_mismatch_count": 0,
    }


def write_reports(report: dict[str, Any]) -> None:
    JSON_REPORT.parent.mkdir(parents=True, exist_ok=True)
    JSON_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    MD_REPORT.write_text(_markdown(report), encoding="utf-8")
    _write_malformed_outputs(report.get("malformed_outputs") or [])
    _write_jsonl_report(SCHEMA_MISMATCH_REPORT, report.get("schema_mismatches") or [])
    _write_jsonl_report(DEBUG_GENERATIONS_REPORT, report.get("debug_generations") or [])


def _normalize_prediction(value: dict[str, Any] | tuple[Any, ...] | str | None) -> dict[str, Any] | None:
    if isinstance(value, tuple):
        value = value[0] if value[0] else (value[2] if len(value) > 2 and value[2] else value[1])
    if isinstance(value, dict):
        return finalize_brain_v4_output(value)
    if isinstance(value, str):
        return parse_brain_v4_output(value)
    return None


def _prediction_schema_exact(value: dict[str, Any] | tuple[Any, ...] | str | None) -> bool:
    return has_exact_brain_v4_schema(_normalize_prediction(value))


def _expected_output(record: dict[str, Any]) -> dict[str, Any]:
    output = record.get("output") or {}
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return output if isinstance(output, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _sample_rows(
    records: list[dict[str, Any]],
    predictions: list[dict[str, Any] | tuple[Any, ...] | str | None],
) -> list[dict[str, Any]]:
    samples = []
    for record, prediction in list(zip(records, predictions))[:5]:
        expected = _expected_output(record)
        samples.append({
            "expected_error_type": expected.get("error_type"),
            "prediction": _normalize_prediction(prediction),
        })
    return samples


def _malformed_rows(
    records: list[dict[str, Any]],
    predictions: list[dict[str, Any] | tuple[Any, ...] | str | None],
) -> list[dict[str, Any]]:
    rows = []
    for index, (record, prediction) in enumerate(zip(records, predictions)):
        if _normalize_prediction(prediction):
            continue
        rows.append({
            "index": index,
            "expected": _expected_output(record),
            "input": record.get("input", ""),
            "raw_output": prediction or "",
        })
    return rows


def _schema_mismatch_rows(
    records: list[dict[str, Any]],
    predictions: list[dict[str, Any] | tuple[Any, ...] | str | None],
) -> list[dict[str, Any]]:
    rows = []
    for index, (record, prediction) in enumerate(zip(records, predictions)):
        normalized = _normalize_prediction(prediction)
        if not normalized or _prediction_schema_exact(prediction):
            continue
        rows.append({
            "index": index,
            "expected": _expected_output(record),
            "input": record.get("input", ""),
            "raw_output": prediction or "",
            "wrong_keys": sorted((prediction or {}).keys()) if isinstance(prediction, dict) else [],
            "normalized_prediction": normalized,
        })
    return rows


def _parse_json_dict(text: Any) -> dict[str, Any]:
    if isinstance(text, dict):
        return text
    if not isinstance(text, str) or not text.strip():
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_malformed_outputs(rows: list[dict[str, Any]]) -> None:
    _write_jsonl_report(MALFORMED_REPORT, rows)


def _write_jsonl_report(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _markdown(report: dict[str, Any]) -> str:
    metrics = report.get("metrics") or {}
    lines = [
        "# GhostFix Brain v4 Evaluation Report",
        "",
        f"Status: `{report.get('status')}`",
        f"Reason: {report.get('reason') or 'n/a'}",
        f"Validation file: `{report.get('validation_file')}`",
        f"Records: {report.get('record_count')}",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key in [
        "valid_json_rate",
        "error_type_accuracy",
        "root_cause_accuracy",
        "safe_to_autofix_accuracy",
        "average_confidence",
        "malformed_output_count",
        "exact_schema_match",
        "schema_mismatch_count",
    ]:
        value = metrics.get(key, 0)
        formatted = f"{value:.4f}" if isinstance(value, float) else str(value)
        lines.append(f"| `{key}` | {formatted} |")
    lines.extend([
        "",
        "## Notes",
        "",
        "- Evaluation is local-only.",
        "- Missing model, adapter, or dependencies produce an unavailable report instead of a crash.",
        "- `safe_to_autofix` accuracy is measured as model-label agreement only; runtime safety policy still controls edits.",
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
