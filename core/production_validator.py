from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence


REPORT_DIR = Path(".ghostfix/reports")
JSON_REPORT = REPORT_DIR / "production_validation.json"
MD_REPORT = REPORT_DIR / "production_validation.md"


@dataclass
class ProductionStep:
    name: str
    command: list[str]
    passed: bool
    returncode: int
    duration_seconds: float
    output_tail: str


def production_commands() -> list[tuple[str, list[str]]]:
    python = sys.executable
    return [
        ("verify-release", [python, "-m", "cli.main", "verify-release"]),
        ("doctor", [python, "-m", "cli.main", "doctor"]),
        ("config show", [python, "-m", "cli.main", "config", "show"]),
        ("context", [python, "-m", "cli.main", "context", "demos/python_name_error.py"]),
        ("run name_error", [python, "-m", "cli.main", "run", "tests/manual_errors/name_error.py"]),
        ("watch python demo", [python, "-m", "cli.main", "watch", "python demos/python_name_error.py", "--no-brain"]),
        ("watch benchmark", [python, "ml/evaluate_watch_mode.py"]),
        (
            "runtime brain route-only",
            [
                python,
                "ml/evaluate_runtime_brain_v4.py",
                "--dir",
                "tests/real_world_failures",
                "--brain-mode",
                "route-only",
            ],
        ),
    ]


def run_production_validation(
    *,
    cwd: Path | None = None,
    runner: Callable[[Sequence[str], Path], subprocess.CompletedProcess] | None = None,
    write_report: bool = True,
) -> dict[str, Any]:
    root = cwd or Path.cwd()
    run = runner or _run_command
    steps = []
    started = time.perf_counter()

    for name, command in production_commands():
        step_started = time.perf_counter()
        result = run(command, root)
        output = "\n".join(part for part in [result.stdout, result.stderr] if part)
        steps.append(
            ProductionStep(
                name=name,
                command=list(command),
                passed=result.returncode == 0,
                returncode=result.returncode,
                duration_seconds=round(time.perf_counter() - step_started, 3),
                output_tail=output[-3000:],
            )
        )

    watch_report = _load_json(root / "ml/reports/watch_mode_eval_report.json")
    runtime_report = _load_json(root / "ml/reports/runtime_brain_v4_report.json")
    report = _build_report(steps, watch_report, runtime_report, round(time.perf_counter() - started, 3))
    if write_report:
        write_production_reports(report, root=root)
    return report


def write_production_reports(report: dict[str, Any], *, root: Path | None = None) -> None:
    base = root or Path.cwd()
    report_dir = base / REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    (base / JSON_REPORT).write_text(json.dumps(report, indent=2), encoding="utf-8")
    (base / MD_REPORT).write_text(_markdown_report(report), encoding="utf-8")


def _run_command(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(command),
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=900,
    )


def _build_report(
    steps: list[ProductionStep],
    watch_report: dict[str, Any],
    runtime_report: dict[str, Any],
    runtime_seconds: float,
) -> dict[str, Any]:
    step_rows = [asdict(step) for step in steps]
    blockers = [step.name for step in steps if not step.passed]
    watch_rows = watch_report.get("rows") or []
    runtime_rows = runtime_report.get("rows") or []
    unsafe_count = sum(1 for row in [*watch_rows, *runtime_rows] if row.get("auto_fix_allowed") is True)
    total_rows = len(watch_rows) + len(runtime_rows)
    unsafe_rate = round(unsafe_count / total_rows, 4) if total_rows else 0.0
    tests_step = next((step for step in steps if step.name == "verify-release"), None)

    benchmark_metrics = {
        "watch_mode": {
            "language_accuracy": watch_report.get("language_accuracy"),
            "runtime_accuracy": watch_report.get("runtime_accuracy"),
            "error_type_accuracy": watch_report.get("error_type_accuracy"),
            "root_cause_keyword_match_rate": watch_report.get("root_cause_keyword_match_rate"),
            "auto_fix_safety_match_rate": watch_report.get("auto_fix_safety_match_rate"),
            "pass_count": watch_report.get("pass_count"),
            "record_count": watch_report.get("record_count"),
        },
        "runtime_brain_v4_route_only": {
            "record_count": runtime_report.get("record_count"),
            "deterministic_solve_rate": runtime_report.get("deterministic_solve_rate"),
            "unresolved_rate": runtime_report.get("unresolved_rate"),
            "unresolved_count": runtime_report.get("unresolved_count"),
            "brain_activation_rate": runtime_report.get("brain_activation_rate"),
            "brain_escalation_rate": runtime_report.get("brain_escalation_rate"),
        },
    }

    return {
        "status": "pass" if not blockers else "fail",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "runtime_seconds": runtime_seconds,
        "tests_passed": bool(tests_step and tests_step.passed),
        "cli_commands_passed": all(step.passed for step in steps),
        "benchmark_metrics": benchmark_metrics,
        "unresolved_rate": runtime_report.get("unresolved_rate"),
        "unsafe_fix_rate": unsafe_rate,
        "unsafe_fix_count": unsafe_count,
        "release_blockers": blockers,
        "steps": step_rows,
        "reports": {
            "json": str(JSON_REPORT),
            "markdown": str(MD_REPORT),
        },
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _markdown_report(report: dict[str, Any]) -> str:
    metrics = report.get("benchmark_metrics") or {}
    watch = metrics.get("watch_mode") or {}
    runtime = metrics.get("runtime_brain_v4_route_only") or {}
    lines = [
        "# GhostFix Local Release Validation",
        "",
        f"- Status: {report['status'].upper()}",
        f"- Tests passed: {'yes' if report['tests_passed'] else 'no'}",
        f"- CLI commands passed: {'yes' if report['cli_commands_passed'] else 'no'}",
        f"- Unresolved rate: {_metric(runtime.get('unresolved_rate'))}",
        f"- Unsafe fix rate: {_metric(report.get('unsafe_fix_rate'))}",
        "- Readiness claim: enterprise-evaluation-ready when all blockers are clear; not a hosted enterprise platform.",
        "",
        "## Benchmark Metrics",
        "",
        f"- Watch language accuracy: {_metric(watch.get('language_accuracy'))}",
        f"- Watch runtime accuracy: {_metric(watch.get('runtime_accuracy'))}",
        f"- Watch error type accuracy: {_metric(watch.get('error_type_accuracy'))}",
        f"- Runtime deterministic solve rate: {_metric(runtime.get('deterministic_solve_rate'))}",
        f"- Runtime unresolved count: {runtime.get('unresolved_count', 'n/a')}",
        "",
        "## Steps",
        "",
        "| Step | Result | Seconds |",
        "| --- | --- | --- |",
    ]
    for step in report["steps"]:
        lines.append(
            f"| {step['name']} | {'PASS' if step['passed'] else 'FAIL'} | {step['duration_seconds']} |"
        )
    blockers = report.get("release_blockers") or []
    lines.extend(["", "## Release Blockers", ""])
    if blockers:
        lines.extend(f"- {blocker}" for blocker in blockers)
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def _metric(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return str(value)
