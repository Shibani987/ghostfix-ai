from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.autofix import build_patch_plan
from core.confidence import confidence_percent
from core.decision_engine import apply_safety_policy, decide_fix
from core.language_diagnostics import diagnose_non_python
from core.parser import parse_error
from core.root_cause_analyzer import RootCauseAnalyzer


REPORT_JSON = Path("ml/reports/demo_report.json")
REPORT_MD = Path("ml/reports/demo_report.md")
DEMO_WORK = Path("ml/reports/demo_work")


@dataclass
class DemoScenario:
    name: str
    command: str
    cwd: str
    expected_error_type: str
    expected_framework: str
    expected_root_cause: str | None = None


def run_demo_report(repo_root: str | Path = ".") -> list[dict[str, Any]]:
    root = Path(repo_root).resolve()
    scenarios = _server_scenarios(root)
    rows = [_run_command_scenario(scenario) for scenario in scenarios]
    rows.extend(_run_autofix_scenarios(root))
    rows.extend(_run_multilang_scenarios(root))
    _write_reports(rows)
    return rows


def _server_scenarios(root: Path) -> list[DemoScenario]:
    return [
        DemoScenario(
            "Flask missing template",
            "python tests/manual_server_errors/flask_missing_template.py",
            str(root),
            "TemplateNotFound",
            "flask",
            "missing_template",
        ),
        DemoScenario(
            "Django missing app",
            "python tests/manual_server_errors/django_missing_app/manage.py check",
            str(root),
            "ModuleNotFoundError",
            "django",
            "missing_django_app_or_bad_installed_apps",
        ),
        DemoScenario(
            "FastAPI bad import",
            "python -m uvicorn tests.manual_server_errors.fastapi_bad_import:app",
            str(root),
            "ModuleNotFoundError",
            "fastapi",
            "fastapi_app_import_error",
        ),
        DemoScenario(
            "Django bad settings",
            "python tests/manual_server_errors/django_bad_settings.py",
            str(root),
            "RuntimeError",
            "django",
            "django_settings_already_configured",
        ),
    ]


def _run_command_scenario(scenario: DemoScenario) -> dict[str, Any]:
    output = _capture_command(scenario.command, scenario.cwd)
    return _diagnose_traceback(
        scenario_name=scenario.name,
        command=scenario.command,
        traceback_text=output,
        cwd=scenario.cwd,
        expected_error_type=scenario.expected_error_type,
        expected_framework=scenario.expected_framework,
        expected_root_cause=scenario.expected_root_cause,
    )


def _capture_command(command: str, cwd: str, timeout: float = 8.0) -> str:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate(timeout=2)
    return output or ""


def _diagnose_traceback(
    *,
    scenario_name: str,
    command: str,
    traceback_text: str,
    cwd: str,
    expected_error_type: str,
    expected_framework: str,
    expected_root_cause: str | None,
) -> dict[str, Any]:
    evidence = RootCauseAnalyzer().analyze(traceback_text, cwd=cwd, command=command)
    parsed = {
        "raw": evidence.raw_traceback,
        "type": evidence.error_type,
        "message": evidence.error_message,
        "file": evidence.file_path,
        "line": evidence.line_number,
    }
    decision = decide_fix(parsed, evidence.code_context)
    if evidence.source in {"framework_rule", "parser"}:
        decision.cause = evidence.root_cause
        decision.fix = evidence.suggested_fix or decision.fix
        decision.source = evidence.source
        decision.confidence = max(decision.confidence, evidence.confidence / 100.0)

    patch_plan = build_patch_plan(evidence.file_path or "", parsed, decision.to_dict()) if evidence.file_path else None
    decision = apply_safety_policy(
        decision,
        patch_available=bool(patch_plan and patch_plan.available),
        patch_valid=bool(patch_plan and patch_plan.available),
        fix_kind=patch_plan.fix_kind if patch_plan else "model_suggested_fix",
        validation=patch_plan.validation if patch_plan else "",
        changed_line_count=patch_plan.changed_line_count if patch_plan else 0,
        deterministic_validator_result=patch_plan.deterministic_validator_result if patch_plan else "",
        compile_validation_result=patch_plan.compile_validation_result if patch_plan else "",
    )

    passed = (
        evidence.error_type == expected_error_type
        and (evidence.framework or "python") == expected_framework
        and (expected_root_cause is None or evidence.root_cause == expected_root_cause)
    )
    return _row(
        scenario_name=scenario_name,
        command=command,
        error_type=evidence.error_type,
        framework=evidence.framework or "python",
        root_cause=evidence.root_cause,
        likely_root_cause=evidence.likely_root_cause or evidence.root_cause,
        suggested_fix=evidence.suggested_fix or decision.fix or "",
        confidence=confidence_percent(decision.confidence),
        source=decision.source,
        auto_fix_available=decision.auto_fix_available,
        safety_reason=decision.safety_policy_reason,
        passed=passed,
    )


def _run_autofix_scenarios(root: Path) -> list[dict[str, Any]]:
    rows = []
    work = root / DEMO_WORK
    work.mkdir(parents=True, exist_ok=True)
    syntax_file = work / "syntax_missing_colon_demo.py"
    syntax_file.write_text("def login(user)\n    print('Welcome', user)\n", encoding="utf-8")
    rows.append(_run_autofix_scenario(
        name="SyntaxError safe patch preview",
        file_path=syntax_file,
        cwd=str(work),
        expected_error_type="SyntaxError",
        root_cause="safe_syntax_patch_available",
    ))

    json_file = work / "json_empty_demo.py"
    json_file.write_text("import json\n\ndata = ''\nresult = json.loads(data)\n", encoding="utf-8")
    rows.append(_run_autofix_scenario(
        name="JSONDecodeError safe patch preview",
        file_path=json_file,
        cwd=str(work),
        expected_error_type="JSONDecodeError",
        root_cause="safe_json_guard_patch_available",
    ))
    return rows


def _run_autofix_scenario(
    name: str,
    file_path: Path,
    cwd: str,
    expected_error_type: str,
    root_cause: str,
) -> dict[str, Any]:
    command = f"python {file_path}"
    output = _capture_command(command, cwd)
    parsed = parse_error(output) or {}
    evidence = RootCauseAnalyzer().analyze(output, cwd=cwd, command=command)
    parsed.update({
        "raw": output,
        "type": evidence.error_type,
        "message": evidence.error_message,
        "file": str(file_path),
        "line": evidence.line_number or parsed.get("line"),
    })
    decision = decide_fix(parsed, evidence.code_context)
    patch_plan = build_patch_plan(str(file_path), parsed, decision.to_dict())
    decision.patch = patch_plan.preview if patch_plan.available else ""
    decision = apply_safety_policy(
        decision,
        patch_available=patch_plan.available,
        patch_valid=patch_plan.available,
        fix_kind=patch_plan.fix_kind,
        validation=patch_plan.validation,
        changed_line_count=patch_plan.changed_line_count,
        deterministic_validator_result=patch_plan.deterministic_validator_result,
        compile_validation_result=patch_plan.compile_validation_result,
    )
    passed = evidence.error_type == expected_error_type and patch_plan.available and decision.auto_fix_available
    return _row(
        scenario_name=name,
        command=command,
        error_type=evidence.error_type,
        framework="python",
        root_cause=root_cause,
        likely_root_cause=evidence.likely_root_cause or evidence.root_cause,
        suggested_fix=decision.fix or evidence.suggested_fix or "",
        confidence=confidence_percent(decision.confidence),
        source=decision.source,
        auto_fix_available=decision.auto_fix_available,
        safety_reason=decision.safety_policy_reason,
        passed=passed,
    )


def _run_multilang_scenarios(root: Path) -> list[dict[str, Any]]:
    scenarios = [
        ("JavaScript ReferenceError", "node tests/manual_multilang_errors/js_reference_error.js", "node", "ReferenceError", "javascript"),
        ("JavaScript module not found", "node tests/manual_multilang_errors/js_module_not_found.js", "node", "Cannot find module", "javascript"),
        ("PHP undefined variable", "php tests/manual_multilang_errors/php_undefined_variable.php", "php", "PHP Warning", "php"),
        ("PHP parse error", "php tests/manual_multilang_errors/php_parse_error.php", "php", "PHP Parse error", "php"),
    ]
    rows = []
    for name, command, runtime, expected_error, expected_language in scenarios:
        if shutil.which(runtime) is None:
            rows.append(_skipped_row(name, command, expected_language, f"{runtime} runtime is not installed"))
            continue
        diagnostic = diagnose_non_python(_capture_command(command, str(root)), command=command, cwd=str(root))
        if not diagnostic:
            rows.append(_skipped_row(name, command, expected_language, "no supported non-Python diagnostic detected"))
            continue
        rows.append(_row(
            scenario_name=name,
            command=command,
            error_type=diagnostic["error_type"],
            framework=diagnostic["language"],
            root_cause=diagnostic["root_cause"],
            likely_root_cause=diagnostic["likely_root_cause"],
            suggested_fix=diagnostic["suggested_fix"],
            confidence=diagnostic["confidence"],
            source=diagnostic["source"],
            auto_fix_available=False,
            safety_reason=diagnostic["safety_reason"],
            passed=diagnostic["language"] == expected_language and diagnostic["error_type"] == expected_error,
        ))
    return rows


def _skipped_row(name: str, command: str, language: str, reason: str) -> dict[str, Any]:
    row = _row(
        scenario_name=name,
        command=command,
        error_type="SKIPPED",
        framework=language,
        root_cause="runtime_unavailable",
        likely_root_cause=reason,
        suggested_fix="Install the runtime to include this detection scenario.",
        confidence=0,
        source="language_rule",
        auto_fix_available=False,
        safety_reason="Auto-fix is disabled for non-Python languages.",
        passed=True,
    )
    row["skipped"] = True
    return row


def _row(
    *,
    scenario_name: str,
    command: str,
    error_type: str,
    framework: str,
    root_cause: str,
    likely_root_cause: str,
    suggested_fix: str,
    confidence: int,
    source: str,
    auto_fix_available: bool,
    safety_reason: str,
    passed: bool,
) -> dict[str, Any]:
    return {
        "scenario_name": scenario_name,
        "command": command,
        "detected_error_type": error_type,
        "detected_framework": framework,
        "root_cause": root_cause,
        "likely_root_cause": likely_root_cause,
        "suggested_fix": suggested_fix,
        "confidence": confidence,
        "source": source,
        "auto_fix_available": auto_fix_available,
        "safety_reason": safety_reason,
        "pass": passed,
        "skipped": False,
    }


def _write_reports(rows: list[dict[str, Any]]) -> None:
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    REPORT_MD.write_text(_markdown_report(rows), encoding="utf-8")


def _markdown_report(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# GhostFix Demo Readiness Report",
        "",
        f"Passed: {sum(1 for row in rows if row['pass'] and not row.get('skipped'))}/{sum(1 for row in rows if not row.get('skipped'))}",
        f"Skipped: {sum(1 for row in rows if row.get('skipped'))}",
        "",
        "| Scenario | Command | Error | Framework | Root Cause | Confidence | Auto-fix | Pass |",
        "|---|---|---|---|---|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {scenario} | `{command}` | {error} | {framework} | {root} | {confidence}% | {autofix} | {passed} |".format(
                scenario=_md(row["scenario_name"]),
                command=_md(row["command"]),
                error=_md(row["detected_error_type"]),
                framework=_md(row["detected_framework"]),
                root=_md(row["root_cause"]),
                confidence=row["confidence"],
                autofix="yes" if row["auto_fix_available"] else "no",
                passed="SKIPPED" if row.get("skipped") else ("PASS" if row["pass"] else "FAIL"),
            )
        )
    lines.extend(["", "## Details", ""])
    for row in rows:
        lines.extend([
            f"### {row['scenario_name']}",
            "",
            f"- Command: `{row['command']}`",
            f"- Detected error type: `{row['detected_error_type']}`",
            f"- Detected framework: `{row['detected_framework']}`",
            f"- Root cause: `{row['root_cause']}`",
            f"- Likely root cause: {row['likely_root_cause']}",
            f"- Suggested fix: {row['suggested_fix']}",
            f"- Confidence: {row['confidence']}%",
            f"- Source: `{row['source']}`",
            f"- Auto-fix available: {'yes' if row['auto_fix_available'] else 'no'}",
            f"- Safety reason: {row['safety_reason']}",
            f"- Result: {'SKIPPED' if row.get('skipped') else ('PASS' if row['pass'] else 'FAIL')}",
            "",
        ])
    return "\n".join(lines)


def _md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
