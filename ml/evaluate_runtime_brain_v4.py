from __future__ import annotations

import json
import argparse
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.context import extract_context
from core.decision_engine import apply_safety_policy, decide_fix
from core.parser import parse_error


MANUAL_ERRORS_DIR = Path("tests/manual_errors")
JSON_REPORT = Path("ml/reports/runtime_brain_v4_report.json")
MD_REPORT = Path("ml/reports/runtime_brain_v4_report.md")
DEFAULT_TIMEOUT_SECONDS = 20.0
EXPECTED_FILENAME = "expected.json"
SAVE_BRAIN_DEBUG_ENV = "GHOSTFIX_SAVE_BRAIN_DEBUG"
FORCE_BRAIN_V4_ENV = "GHOSTFIX_FORCE_BRAIN_V4"
BRAIN_MODE_ENV = "GHOSTFIX_BRAIN_MODE"
DEFAULT_BRAIN_MODE = "route-only"
BRAIN_MODES = {"auto", "off", "route-only", "generate"}
BRAIN_DEBUG_DIR = Path("ml/reports/brain_debug")
ROOT_CAUSE_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "can",
    "cannot",
    "code",
    "does",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
    "without",
}


def evaluate_runtime_cases(
    manual_dir: Path = MANUAL_ERRORS_DIR,
    *,
    limit: int | None = None,
    brain: bool = True,
    brain_mode: str = DEFAULT_BRAIN_MODE,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    brain_mode = _normalize_brain_mode(brain_mode, brain=brain)
    rows = []
    started = time.perf_counter()
    paths = sorted(manual_dir.glob("*.py"))
    if limit is not None:
        paths = paths[: max(0, limit)]
    expected = _load_expected_metadata(manual_dir)

    print(
        f"Runtime Brain v4 benchmark: total files={len(paths)}, brain_mode={brain_mode}, timeout={timeout:g}s",
        flush=True,
    )

    with _brain_mode_env(brain_mode):
        if brain_mode != "off":
            print("Brain v4: available for gated decisions; lazy load only when needed.", flush=True)
        brain_status = (
            {"available": True, "reason": "Deferred until a gated decision needs Brain v4."}
            if brain_mode != "off"
            else {"available": False, "reason": "Brain disabled"}
        )
        if brain_mode != "off":
            preload_reason = _truncate(str(brain_status.get("reason", "")), limit=240)
            print(
                "Brain v4 load: "
                f"{'deferred' if brain_status.get('available') else 'unavailable'}"
                f" ({preload_reason})",
                flush=True,
            )

        for index, path in enumerate(paths, start=1):
            print(f"[{index}/{len(paths)}] {path}", flush=True)
            row = _evaluate_file(path, timeout=timeout)
            _score_row(row, expected.get(path.name))
            rows.append(row)
            print(
                f"[{index}/{len(paths)}] {path.name} completed in {row['runtime_seconds']:.3f}s",
                flush=True,
            )

    errored = [row for row in rows if row["detected_error_type"]]
    scoring = _scoring_summary(rows, expected_present=bool(expected))
    return {
        "status": "ok",
        "manual_errors_dir": str(manual_dir),
        "execution_mode": "in-process-decision",
        "brain_enabled": brain_mode != "off",
        "brain_mode": brain_mode,
        "brain_generation_allowed": brain_mode in {"auto", "generate"},
        "brain_preload": brain_status,
        "timeout_seconds": timeout,
        "limit": limit,
        "record_count": len(rows),
        "detected_error_count": len(errored),
        "runtime_seconds": round(time.perf_counter() - started, 3),
        "expected_metadata_file": str(manual_dir / EXPECTED_FILENAME) if expected else "",
        "expected_record_count": len(expected),
        **scoring,
        "rows": rows,
    }


@contextmanager
def _brain_mode_env(brain_mode: str):
    previous = os.environ.get("GHOSTFIX_BRAIN_V4")
    previous_mode = os.environ.get(BRAIN_MODE_ENV)
    previous_force = os.environ.get(FORCE_BRAIN_V4_ENV)
    if brain_mode != "off":
        os.environ["GHOSTFIX_BRAIN_V4"] = "1"
    else:
        os.environ.pop("GHOSTFIX_BRAIN_V4", None)
    os.environ[BRAIN_MODE_ENV] = brain_mode
    if brain_mode == "generate":
        os.environ[FORCE_BRAIN_V4_ENV] = "1"
    elif previous_force is None:
        os.environ.pop(FORCE_BRAIN_V4_ENV, None)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("GHOSTFIX_BRAIN_V4", None)
        else:
            os.environ["GHOSTFIX_BRAIN_V4"] = previous
        if previous_mode is None:
            os.environ.pop(BRAIN_MODE_ENV, None)
        else:
            os.environ[BRAIN_MODE_ENV] = previous_mode
        if previous_force is None:
            os.environ.pop(FORCE_BRAIN_V4_ENV, None)
        else:
            os.environ[FORCE_BRAIN_V4_ENV] = previous_force


def _normalize_brain_mode(brain_mode: str, *, brain: bool = True) -> str:
    if not brain:
        return "off"
    mode = str(brain_mode or DEFAULT_BRAIN_MODE).strip().lower()
    if mode not in BRAIN_MODES:
        raise ValueError(f"Unsupported brain mode: {brain_mode}")
    return mode


def _preload_brain_v4() -> dict[str, Any]:
    try:
        from core import decision_engine

        runner = decision_engine._brain_v4_runtime()
        status = runner.load()
        return {"available": status.available, "reason": status.reason}
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}


def _evaluate_file(path: Path, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    started = time.perf_counter()
    stdout = ""
    stderr = ""
    parsed = None
    decision = None
    safe_to_autofix = False

    try:
        process = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = process.stdout or ""
        stderr = process.stderr or ""
        parsed = parse_error(stderr)
        if parsed:
            parsed["verbose"] = False
            context = extract_context(str(path), stderr)
            decision = decide_fix(parsed, context)
            safe_to_autofix = bool(_decision_value(decision, "auto_fix_available", False))
            decision = apply_safety_policy(decision, patch_available=False, patch_valid=False)
    except Exception as exc:
        stderr = f"{type(exc).__name__}: {exc}"

    runtime = round(time.perf_counter() - started, 3)
    return _row_from_result(path, parsed, decision, stdout, stderr, runtime, safe_to_autofix=safe_to_autofix)


def _row_from_result(
    path: Path,
    parsed: dict[str, Any] | None,
    decision: Any,
    stdout: str,
    stderr: str,
    runtime_seconds: float,
    safe_to_autofix: bool = False,
) -> dict[str, Any]:
    row = {
        "file": str(path),
        "detected_error_type": parsed.get("type") if parsed else "",
        "cause": _decision_value(decision, "cause", ""),
        "fix": _decision_value(decision, "fix", ""),
        "source": _decision_value(decision, "source", ""),
        "brain_version": _decision_value(decision, "brain_version", ""),
        "brain_confidence": _decision_value(decision, "brain_confidence", 0.0),
        "brain_used": bool(_decision_value(decision, "brain_used", False)),
        "brain_escalated": bool(_decision_value(decision, "brain_escalated", False)),
        "brain_raw_available": bool(_decision_value(decision, "brain_raw_available", False)),
        "brain_output_valid": bool(_decision_value(decision, "brain_output_valid", False)),
        "brain_failure_reason": _decision_value(decision, "brain_failure_reason", "none") or "none",
        "brain_guard_reason": _compact_text(_decision_value(decision, "brain_guard_reason", "") or "", limit=360),
        "brain_generation_seconds": float(_decision_value(decision, "brain_generation_seconds", 0.0) or 0.0),
        "brain_skipped_reason": _compact_text(_decision_value(decision, "brain_skipped_reason", "") or "", limit=360),
        "decision_source_path": _decision_value(decision, "decision_source_path", "") or _infer_decision_source_path(decision),
        "escalation_reason": _decision_value(decision, "escalation_reason", "none") or "none",
        "safe_to_autofix": safe_to_autofix,
        "auto_fix_available": bool(_decision_value(decision, "auto_fix_available", False)),
        "manual_review_required": bool(_decision_value(decision, "manual_review_required", True)),
        "runtime_seconds": runtime_seconds,
        "stdout": _truncate(stdout),
        "stderr": _truncate(stderr),
    }
    if _save_brain_debug_enabled():
        row["brain_debug"] = _decision_value(decision, "brain_debug", None)
    return row


def _infer_decision_source_path(decision: Any) -> str:
    if decision is None:
        return "none"
    source = str(_decision_value(decision, "source", "") or "")
    if source == "fallback":
        return "fallback"
    if source == "local_llm":
        return "local_llm"
    if source == "llm":
        return "llm"
    if "retriever" in source:
        return "retriever only"
    if source in {"rule", "hybrid: memory/retriever/brain"}:
        return "rules only"
    return source or "none"


def _load_expected_metadata(manual_dir: Path) -> dict[str, dict[str, Any]]:
    expected_path = manual_dir / EXPECTED_FILENAME
    if not expected_path.exists():
        return {}
    try:
        data = json.loads(expected_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid benchmark metadata JSON: {expected_path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Expected benchmark metadata must be an object: {expected_path}")
    return {str(name): value for name, value in data.items() if isinstance(value, dict)}


def _score_row(row: dict[str, Any], expected: dict[str, Any] | None) -> None:
    expected_error_type = ""
    expected_safe_to_autofix = None
    expected_manual_review = None
    error_type_match = None
    safe_to_autofix_match = None
    manual_review_match = None
    root_cause_match = None

    if expected:
        expected_error_type = str(expected.get("expected_error_type") or "")
        expected_safe_to_autofix = bool(expected.get("safe_to_autofix", False))
        expected_manual_review = bool(expected.get("expected_manual_review_required", True))
        error_type_match = row["detected_error_type"] == expected_error_type
        safe_to_autofix_match = bool(row.get("safe_to_autofix")) == expected_safe_to_autofix
        manual_review_match = bool(row["manual_review_required"]) == expected_manual_review
        root_cause_match = _root_cause_matches(
            actual=str(row.get("cause") or ""),
            expected=str(expected.get("expected_root_cause") or ""),
        )

    row.update(
        {
            "expected_error_type": expected_error_type,
            "error_type_match": error_type_match,
            "expected_safe_to_autofix": expected_safe_to_autofix,
            "safe_to_autofix_match": safe_to_autofix_match,
            "expected_manual_review_required": expected_manual_review,
            "manual_review_match": manual_review_match,
            "root_cause_match": root_cause_match,
        }
    )


def _root_cause_matches(*, actual: str, expected: str) -> bool:
    actual_norm = _normalize_match_text(actual)
    expected_norm = _normalize_match_text(expected)
    if not actual_norm or not expected_norm:
        return False
    if actual_norm in expected_norm or expected_norm in actual_norm:
        return True

    important_words = _important_words(expected_norm)
    if not important_words:
        return False
    matched_words = [word for word in important_words if word in actual_norm]
    return len(matched_words) >= min(2, len(important_words))


def _normalize_match_text(text: str) -> str:
    return " ".join(str(text or "").lower().replace("_", " ").split())


def _important_words(text: str) -> list[str]:
    words = []
    for raw_word in text.split():
        word = "".join(ch for ch in raw_word if ch.isalnum())
        if len(word) < 4 or word in ROOT_CAUSE_STOPWORDS:
            continue
        words.append(word)
    return words


def _scoring_summary(rows: list[dict[str, Any]], *, expected_present: bool) -> dict[str, Any]:
    average_runtime = _rate([float(row.get("runtime_seconds") or 0.0) for row in rows], average=True)
    routing = _routing_summary(rows)
    if not expected_present:
        return {
            "error_type_accuracy": None,
            "root_cause_match_rate": None,
            "safe_to_autofix_accuracy": None,
            "manual_review_accuracy": None,
            "average_runtime_seconds": average_runtime,
            **routing,
        }
    return {
        "error_type_accuracy": _match_rate(rows, "error_type_match"),
        "root_cause_match_rate": _match_rate(rows, "root_cause_match"),
        "safe_to_autofix_accuracy": _match_rate(rows, "safe_to_autofix_match"),
        "manual_review_accuracy": _match_rate(rows, "manual_review_match"),
        "average_runtime_seconds": average_runtime,
        **routing,
    }


def _routing_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    brain_rows = [row for row in rows if row.get("brain_used")]
    escalated_rows = [row for row in rows if _is_brain_escalated_row(row)]
    deterministic_rows = [row for row in rows if _is_deterministic_row(row)]
    retriever_rows = [row for row in rows if _uses_retriever(row)]
    brain_assisted_rows = [row for row in rows if _is_brain_assisted_row(row)]
    unresolved_rows = [row for row in rows if _is_unresolved_row(row)]
    brain_failure_rows = [row for row in rows if _is_brain_escalated_row(row)]
    usable_brain_rows = [row for row in brain_failure_rows if row.get("brain_failure_reason") == "success"]

    return {
        "brain_used_count": len(brain_rows),
        "brain_skipped_count": total - len(brain_rows),
        "brain_used_percent": round((len(brain_rows) / total), 4) if total else None,
        "brain_activation_count": len(escalated_rows),
        "brain_activation_rate": round((len(escalated_rows) / total), 4) if total else None,
        "brain_escalation_count": len(escalated_rows),
        "brain_escalation_rate": round((len(escalated_rows) / total), 4) if total else None,
        "deterministic_rule_count": len(deterministic_rows),
        "deterministic_solve_count": len(deterministic_rows),
        "deterministic_solve_rate": round((len(deterministic_rows) / total), 4) if total else None,
        "retriever_only_count": sum(1 for row in rows if row.get("decision_source_path") == "retriever only"),
        "memory_hit_count": sum(1 for row in rows if str(row.get("decision_source_path") or "").startswith("memory")),
        "fallback_count": sum(1 for row in rows if str(row.get("decision_source_path") or "").startswith("fallback")),
        "unresolved_count": len(unresolved_rows),
        "unresolved_rate": round((len(unresolved_rows) / total), 4) if total else None,
        "usable_brain_output_rate": _reason_rate(brain_failure_rows, "success"),
        "malformed_output_rate": _reason_rate(brain_failure_rows, "malformed_output"),
        "generic_response_rate": _reason_rate(brain_failure_rows, "generic_response"),
        "timeout_rate": _reason_rate(brain_failure_rows, "timeout"),
        "guard_suppression_rate": _guard_suppression_rate(brain_failure_rows),
        "usable_brain_output_count": len(usable_brain_rows),
        "malformed_output_count": _reason_count(brain_failure_rows, "malformed_output"),
        "generic_response_count": _reason_count(brain_failure_rows, "generic_response"),
        "timeout_count": _reason_count(brain_failure_rows, "timeout"),
        "guard_suppression_count": sum(1 for row in brain_failure_rows if row.get("brain_failure_reason") == "suppressed_by_guard"),
        "avg_brain_generation_seconds": _average_brain_generation(brain_failure_rows),
        "average_deterministic_runtime_seconds": _average_runtime(deterministic_rows),
        "average_retriever_runtime_seconds": _average_runtime(retriever_rows),
        "average_brain_assisted_runtime_seconds": _average_runtime(brain_assisted_rows),
    }


def _is_deterministic_row(row: dict[str, Any]) -> bool:
    route = str(row.get("decision_source_path") or "")
    return "rules" in route and not row.get("brain_used")


def _uses_retriever(row: dict[str, Any]) -> bool:
    return "retriever" in str(row.get("decision_source_path") or "")


def _is_brain_assisted_row(row: dict[str, Any]) -> bool:
    return _is_brain_escalated_row(row)


def _is_brain_escalated_row(row: dict[str, Any]) -> bool:
    return bool(row.get("brain_escalated")) or str(row.get("decision_source_path") or "").endswith("-> brain")


def _is_unresolved_row(row: dict[str, Any]) -> bool:
    route = str(row.get("decision_source_path") or "")
    return route.startswith("fallback") and not row.get("brain_used")


def _reason_count(rows: list[dict[str, Any]], reason: str) -> int:
    return sum(1 for row in rows if row.get("brain_failure_reason") == reason)


def _reason_rate(rows: list[dict[str, Any]], reason: str) -> float | None:
    if not rows:
        return None
    return round(_reason_count(rows, reason) / len(rows), 4)


def _guard_suppression_rate(rows: list[dict[str, Any]]) -> float | None:
    if not rows:
        return None
    guarded = sum(1 for row in rows if row.get("brain_failure_reason") == "suppressed_by_guard")
    return round(guarded / len(rows), 4)


def _average_runtime(rows: list[dict[str, Any]]) -> float | None:
    return _rate([float(row.get("runtime_seconds") or 0.0) for row in rows], average=True)


def _average_brain_generation(rows: list[dict[str, Any]]) -> float | None:
    values = [float(row.get("brain_generation_seconds") or 0.0) for row in rows if row.get("brain_generation_seconds")]
    return _rate(values, average=True)


def _match_rate(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row.get(key) for row in rows if row.get(key) is not None]
    return _rate([1.0 if value else 0.0 for value in values])


def _rate(values: list[float], *, average: bool = False) -> float | None:
    if not values:
        return None
    value = sum(values) / len(values)
    return round(value, 3 if average else 4)


def _decision_value(decision: Any, key: str, default: Any = "") -> Any:
    if decision is None:
        return default
    if isinstance(decision, dict):
        return decision.get(key, default)
    return getattr(decision, key, default)


def _truncate(text: str, limit: int = 1200) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _compact_text(text: str, limit: int = 1200) -> str:
    return _truncate(" ".join(str(text or "").split()), limit=limit)


def write_reports(report: dict[str, Any]) -> None:
    JSON_REPORT.parent.mkdir(parents=True, exist_ok=True)
    if _save_brain_debug_enabled():
        _write_brain_debug_artifacts(report)
    JSON_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    MD_REPORT.write_text(render_markdown(report), encoding="utf-8")


def _save_brain_debug_enabled() -> bool:
    return os.getenv(SAVE_BRAIN_DEBUG_ENV) == "1"


def _write_brain_debug_artifacts(report: dict[str, Any]) -> None:
    BRAIN_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    for row in report.get("rows", []):
        debug = row.get("brain_debug")
        if not isinstance(debug, dict):
            continue
        case_name = Path(row.get("file") or "case").stem
        artifact = {
            "file": row.get("file"),
            "detected_error_type": row.get("detected_error_type"),
            "brain_failure_reason": row.get("brain_failure_reason"),
            "brain_guard_reason": row.get("brain_guard_reason"),
            "prompt": debug.get("prompt", ""),
            "raw_generation": debug.get("raw_generation", ""),
            "parsed_output": debug.get("parsed_output"),
            "normalized_output": debug.get("normalized_output") or debug.get("final_normalized_output"),
            "final_normalized_output": debug.get("final_normalized_output"),
            "failure_reason": row.get("brain_failure_reason"),
        }
        (BRAIN_DEBUG_DIR / f"{case_name}.json").write_text(
            json.dumps(artifact, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# GhostFix Brain v4 Runtime Report",
        "",
        f"- Manual errors dir: `{report['manual_errors_dir']}`",
        f"- Execution mode: `{report.get('execution_mode', 'in-process-decision')}`",
        f"- Brain enabled: {'yes' if report.get('brain_enabled', True) else 'no'}",
        f"- Brain mode: `{report.get('brain_mode', DEFAULT_BRAIN_MODE)}`",
        f"- Brain generation allowed: {'yes' if report.get('brain_generation_allowed', True) else 'no'}",
        f"- Timeout seconds: {report.get('timeout_seconds', DEFAULT_TIMEOUT_SECONDS)}",
        f"- Files evaluated: {report['record_count']}",
        f"- Errors detected: {report['detected_error_count']}",
        f"- Total runtime seconds: {report['runtime_seconds']}",
        f"- Average runtime seconds: {_metric_value(report.get('average_runtime_seconds'))}",
    ]
    if report.get("expected_metadata_file"):
        lines.extend(
            [
                f"- Expected metadata: `{report['expected_metadata_file']}`",
                f"- Error type accuracy: {_percent_metric(report.get('error_type_accuracy'))}",
                f"- Root cause match rate: {_percent_metric(report.get('root_cause_match_rate'))}",
                f"- Safe-to-autofix accuracy: {_percent_metric(report.get('safe_to_autofix_accuracy'))}",
                f"- Manual review accuracy: {_percent_metric(report.get('manual_review_accuracy'))}",
            ]
        )
    lines.extend(
        [
            "",
            "## Decision Routing Summary",
            "",
            f"- Brain used: {report.get('brain_used_count', 0)}/{report['record_count']} cases ({_percent_metric(report.get('brain_used_percent'))})",
            f"- Brain activations: {report.get('brain_activation_count', 0)}/{report['record_count']} cases ({_percent_metric(report.get('brain_activation_rate'))})",
            f"- Brain skipped: {report.get('brain_skipped_count', 0)}",
            f"- Deterministic rule count: {report.get('deterministic_rule_count', 0)}",
            f"- Retriever-only count: {report.get('retriever_only_count', 0)}",
            f"- Memory hit count: {report.get('memory_hit_count', 0)}",
            f"- Fallback count: {report.get('fallback_count', 0)}",
            f"- Avg deterministic runtime: {_seconds_metric(report.get('average_deterministic_runtime_seconds'))}",
            f"- Avg retriever runtime: {_seconds_metric(report.get('average_retriever_runtime_seconds'))}",
            f"- Avg brain-assisted runtime: {_seconds_metric(report.get('average_brain_assisted_runtime_seconds'))}",
            f"- Avg Brain generation: {_seconds_metric(report.get('avg_brain_generation_seconds'))}",
            "",
            "## Brain Escalation Analysis",
            "",
            f"- Brain activations: {report.get('brain_activation_count', 0)}/{report['record_count']} cases ({_percent_metric(report.get('brain_activation_rate'))})",
            f"- Brain escalations: {report.get('brain_escalation_count', 0)}/{report['record_count']} cases ({_percent_metric(report.get('brain_escalation_rate'))})",
            f"- Deterministic solve rate: {_percent_metric(report.get('deterministic_solve_rate'))}",
            f"- Unresolved rate: {_percent_metric(report.get('unresolved_rate'))}",
            f"- Unresolved count: {report.get('unresolved_count', 0)}",
            "",
            "## Brain Failure Analysis",
            "",
            f"- Usable Brain output rate: {_percent_metric(report.get('usable_brain_output_rate'))}",
            f"- Malformed output rate: {_percent_metric(report.get('malformed_output_rate'))}",
            f"- Generic response rate: {_percent_metric(report.get('generic_response_rate'))}",
            f"- Timeout rate: {_percent_metric(report.get('timeout_rate'))}",
            f"- Guard suppression rate: {_percent_metric(report.get('guard_suppression_rate'))}",
            f"- Usable Brain output count: {report.get('usable_brain_output_count', 0)}",
            f"- Malformed output count: {report.get('malformed_output_count', 0)}",
            f"- Generic response count: {report.get('generic_response_count', 0)}",
            f"- Timeout count: {report.get('timeout_count', 0)}",
            f"- Guard suppression count: {report.get('guard_suppression_count', 0)}",
            f"- Avg Brain generation seconds: {_metric_value(report.get('avg_brain_generation_seconds'))}",
            "",
            "| File | Error | Source | Brain Used | Brain Skip Reason | Brain | Brain Conf | Auto-fix | Manual Review | Runtime |",
            "| --- | --- | --- | --- | --- | --- | ---: | --- | --- | ---: |",
        ]
    )
    for row in report["rows"]:
        lines.append(
            "| {file} | {error} | {source} | {brain_used} | {skip_reason} | {brain} | {brain_conf:.0%} | {autofix} | {review} | {runtime:.3f} |".format(
                file=Path(row["file"]).name,
                error=row["detected_error_type"] or "none",
                source=row["source"] or "none",
                brain_used="yes" if row.get("brain_used") else "no",
                skip_reason=_markdown_cell(row.get("brain_skipped_reason") or ""),
                brain=row["brain_version"] or "none",
                brain_conf=float(row["brain_confidence"] or 0),
                autofix="yes" if row["auto_fix_available"] else "no",
                review="yes" if row["manual_review_required"] else "no",
                runtime=float(row["runtime_seconds"]),
            )
        )
    lines.extend(["", "## Details", ""])
    for row in report["rows"]:
        lines.extend(
            [
                f"### {Path(row['file']).name}",
                "",
                f"- Error: `{row['detected_error_type'] or 'none'}`",
                f"- Cause: {row['cause'] or ''}",
                f"- Fix: {row['fix'] or ''}",
                f"- Source: `{row['source'] or 'none'}`",
                f"- Brain: `{row['brain_version'] or 'none'}` ({float(row['brain_confidence'] or 0):.0%})",
                f"- Brain used: {'yes' if row.get('brain_used') else 'no'}",
                f"- Brain escalated: {'yes' if row.get('brain_escalated') else 'no'}",
                f"- Brain raw available: {'yes' if row.get('brain_raw_available') else 'no'}",
                f"- Brain output valid: {'yes' if row.get('brain_output_valid') else 'no'}",
                f"- Brain failure reason: {row.get('brain_failure_reason') or 'none'}",
                f"- Brain guard reason: {row.get('brain_guard_reason') or ''}",
                f"- Brain generation seconds: {float(row.get('brain_generation_seconds') or 0.0):.3f}",
                f"- Brain skipped reason: {row.get('brain_skipped_reason') or ''}",
                f"- Decision source path: {row.get('decision_source_path') or 'none'}",
                f"- Escalation reason: {row.get('escalation_reason') or 'none'}",
                f"- Safe-to-autofix: {_yes_no(row.get('safe_to_autofix'))}",
                f"- Auto-fix available: {'yes' if row['auto_fix_available'] else 'no'}",
                f"- Manual review required: {'yes' if row['manual_review_required'] else 'no'}",
                f"- Runtime seconds: {float(row['runtime_seconds']):.3f}",
            ]
        )
        if row.get("expected_error_type"):
            lines.extend(
                [
                    f"- Expected error type: `{row['expected_error_type']}`",
                    f"- Error type match: {_yes_no(row.get('error_type_match'))}",
                    f"- Expected safe-to-autofix: {_yes_no(row.get('expected_safe_to_autofix'))}",
                    f"- Safe-to-autofix match: {_yes_no(row.get('safe_to_autofix_match'))}",
                    f"- Expected manual review required: {_yes_no(row.get('expected_manual_review_required'))}",
                    f"- Manual review match: {_yes_no(row.get('manual_review_match'))}",
                    f"- Root cause match: {_yes_no(row.get('root_cause_match'))}",
                ]
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _markdown_cell(text: str) -> str:
    return str(text or "").replace("|", "\\|")


def _metric_value(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def _seconds_metric(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{_metric_value(value)}s"


def _percent_metric(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return str(value)


def _yes_no(value: Any) -> str:
    if value is None:
        return "n/a"
    return "yes" if bool(value) else "no"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate GhostFix runtime speed with Brain v4.")
    parser.add_argument(
        "--manual-dir",
        "--dir",
        dest="manual_dir",
        default=str(MANUAL_ERRORS_DIR),
        help="Directory of Python error files.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of files to evaluate.")
    parser.add_argument(
        "--brain",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable Brain v4 for runtime decisions. Use --no-brain to disable it.",
    )
    parser.add_argument(
        "--brain-mode",
        choices=sorted(BRAIN_MODES),
        default=DEFAULT_BRAIN_MODE,
        help="Brain runtime mode: off, route-only, auto, or generate. Benchmark default is route-only.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Timeout in seconds for running each manual error file.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    report = evaluate_runtime_cases(
        Path(args.manual_dir),
        limit=args.limit,
        brain=args.brain,
        brain_mode=args.brain_mode,
        timeout=args.timeout,
    )
    write_reports(report)
    print(f"Runtime Brain v4 JSON report: {JSON_REPORT}", flush=True)
    print(f"Runtime Brain v4 Markdown report: {MD_REPORT}", flush=True)
    print(f"Evaluated {report['record_count']} files in {report['runtime_seconds']} seconds.")
    print(f"Brain mode: {report.get('brain_mode', DEFAULT_BRAIN_MODE)}", flush=True)
    print(
        "Brain used: "
        f"{report.get('brain_used_count', 0)}/{report['record_count']} cases "
        f"({_percent_metric(report.get('brain_used_percent'))})",
        flush=True,
    )
    print(
        "Brain activations: "
        f"{report.get('brain_activation_count', 0)}/{report['record_count']} cases "
        f"({_percent_metric(report.get('brain_activation_rate'))})",
        flush=True,
    )
    print(f"Avg deterministic runtime: {_seconds_metric(report.get('average_deterministic_runtime_seconds'))}", flush=True)
    print(f"Avg brain-assisted runtime: {_seconds_metric(report.get('average_brain_assisted_runtime_seconds'))}", flush=True)
    print(f"Avg Brain generation: {_seconds_metric(report.get('avg_brain_generation_seconds'))}", flush=True)
    print(
        "Brain escalations: "
        f"{report.get('brain_escalation_count', 0)}/{report['record_count']} cases "
        f"({_percent_metric(report.get('brain_escalation_rate'))})",
        flush=True,
    )
    print(f"Deterministic solve rate: {_percent_metric(report.get('deterministic_solve_rate'))}", flush=True)
    print(f"Unresolved rate: {_percent_metric(report.get('unresolved_rate'))}", flush=True)
    print(f"Usable Brain output rate: {_percent_metric(report.get('usable_brain_output_rate'))}", flush=True)
    print(f"Generic response rate: {_percent_metric(report.get('generic_response_rate'))}", flush=True)
    print(f"Malformed output rate: {_percent_metric(report.get('malformed_output_rate'))}", flush=True)
    if _save_brain_debug_enabled():
        print(f"Brain debug artifacts: {BRAIN_DEBUG_DIR}", flush=True)


if __name__ == "__main__":
    main()
