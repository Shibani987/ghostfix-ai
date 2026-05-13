from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.decision_engine import apply_safety_policy, decide_fix
from core.language_diagnostics import diagnose_non_python
from core.parser import extract_runtime_error, parse_error
from core.root_cause_analyzer import RootCauseAnalyzer


CASES_DIR = Path("tests/watch_mode_cases")
EXPECTED_FILENAME = "expected.json"
JSON_REPORT = Path("ml/reports/watch_mode_eval_report.json")
MD_REPORT = Path("ml/reports/watch_mode_eval_report.md")


def evaluate_watch_mode(cases_dir: Path = CASES_DIR) -> dict[str, Any]:
    started = time.perf_counter()
    expected = _load_expected(cases_dir)
    rows = []
    for path in sorted(cases_dir.glob("*.log")):
        row = _evaluate_log(path)
        _score_row(row, expected.get(path.name, {}))
        rows.append(row)

    return {
        "status": "ok",
        "cases_dir": str(cases_dir),
        "expected_metadata_file": str(cases_dir / EXPECTED_FILENAME),
        "record_count": len(rows),
        "runtime_seconds": round(time.perf_counter() - started, 3),
        **_metrics(rows),
        "rows": rows,
    }


def _evaluate_log(path: Path) -> dict[str, Any]:
    output = path.read_text(encoding="utf-8")
    command = _command_for_case(path.name)
    extracted = extract_runtime_error(output, command=command)
    prediction = _prediction_from_extracted(extracted, output, command)
    return {
        "case": path.name,
        "command": command,
        "detected_language": prediction["language"],
        "detected_runtime": prediction["runtime"],
        "detected_error_type": prediction["error_type"],
        "root_cause": prediction["root_cause"],
        "suggested_fix": prediction["suggested_fix"],
        "auto_fix_allowed": prediction["auto_fix_allowed"],
        "source": prediction["source"],
    }


def _prediction_from_extracted(extracted: dict[str, Any] | None, output: str, command: str) -> dict[str, Any]:
    if extracted and extracted.get("kind") == "python_traceback":
        block = extracted.get("error_block") or output
        evidence = RootCauseAnalyzer().analyze(block, cwd=str(ROOT), command=command)
        parsed = parse_error(block) or extracted
        decision = decide_fix(parsed, evidence.code_context)
        decision = apply_safety_policy(decision, patch_available=False, patch_valid=False)
        root_cause = evidence.likely_root_cause or evidence.root_cause or decision.cause or ""
        return {
            "language": "python",
            "runtime": evidence.framework or extracted.get("framework") or "python",
            "error_type": evidence.error_type or extracted.get("type") or "",
            "root_cause": root_cause,
            "suggested_fix": evidence.suggested_fix or decision.fix or "",
            "auto_fix_allowed": bool(decision.auto_fix_available),
            "source": evidence.source,
        }

    if extracted and extracted.get("kind") in {"port_in_use", "missing_env_var"}:
        return {
            "language": extracted.get("language") or "unknown",
            "runtime": _runtime_from_extracted(extracted, command),
            "error_type": extracted.get("type") or "",
            "root_cause": _root_cause_for_structured_log(extracted),
            "suggested_fix": _suggest_fix_for_structured_log(extracted),
            "auto_fix_allowed": False,
            "source": "runtime_parser",
        }

    diagnostic = diagnose_non_python(output, command=command)
    if diagnostic:
        return {
            "language": diagnostic.get("language") or "unknown",
            "runtime": _runtime_from_non_python(command, diagnostic),
            "error_type": diagnostic.get("error_type") or "",
            "root_cause": diagnostic.get("likely_root_cause") or diagnostic.get("root_cause") or "",
            "suggested_fix": diagnostic.get("suggested_fix") or "",
            "auto_fix_allowed": bool(diagnostic.get("auto_fix_available")),
            "source": diagnostic.get("source") or "language_rule",
        }

    return {
        "language": (extracted or {}).get("language") or "unknown",
        "runtime": _runtime_from_extracted(extracted or {}, command),
        "error_type": (extracted or {}).get("type") or "UnknownError",
        "root_cause": (extracted or {}).get("message") or "Low confidence: needs manual review.",
        "suggested_fix": "Review the log manually.",
        "auto_fix_allowed": False,
        "source": "fallback",
    }


def _runtime_from_extracted(extracted: dict[str, Any], command: str) -> str:
    kind = extracted.get("kind")
    if kind == "port_in_use":
        return "port"
    if kind == "missing_env_var":
        return "env"
    framework = extracted.get("framework")
    if framework and framework != "unknown":
        return framework
    return _runtime_from_command(command)


def _runtime_from_non_python(command: str, diagnostic: dict[str, Any]) -> str:
    if "npm" in command.lower():
        return "npm"
    return diagnostic.get("framework") or _runtime_from_command(command)


def _runtime_from_command(command: str) -> str:
    command_lower = command.lower()
    if "manage.py" in command_lower:
        return "django"
    if "uvicorn" in command_lower:
        return "fastapi"
    if "npm" in command_lower:
        return "npm"
    if "node" in command_lower:
        return "node"
    if "python" in command_lower:
        return "python"
    return "unknown"


def _root_cause_for_structured_log(extracted: dict[str, Any]) -> str:
    if extracted.get("kind") == "port_in_use":
        return "The configured server port is already in use by another process."
    if extracted.get("kind") == "missing_env_var":
        return "A required environment variable is missing from the server process."
    return extracted.get("message") or ""


def _suggest_fix_for_structured_log(extracted: dict[str, Any]) -> str:
    if extracted.get("kind") == "port_in_use":
        return "Stop the process using the port or configure a different server port."
    if extracted.get("kind") == "missing_env_var":
        return "Set the missing environment variable before starting the server."
    return "Review the structured log and rerun the server."


def _score_row(row: dict[str, Any], expected: dict[str, Any]) -> None:
    row["expected_language"] = expected.get("expected_language", "")
    row["expected_runtime"] = expected.get("expected_runtime", "")
    row["expected_error_type"] = expected.get("expected_error_type", "")
    row["expected_root_cause_keyword"] = expected.get("expected_root_cause_keyword", "")
    row["expected_auto_fix_allowed"] = bool(expected.get("expected_auto_fix_allowed", False))
    row["language_match"] = row["detected_language"] == row["expected_language"]
    row["runtime_match"] = row["detected_runtime"] == row["expected_runtime"]
    row["error_type_match"] = row["detected_error_type"] == row["expected_error_type"]
    row["root_cause_keyword_match"] = _contains_keyword(row["root_cause"], row["expected_root_cause_keyword"])
    row["auto_fix_safety_match"] = row["auto_fix_allowed"] == row["expected_auto_fix_allowed"]
    row["pass"] = all(
        row[key]
        for key in (
            "language_match",
            "runtime_match",
            "error_type_match",
            "root_cause_keyword_match",
            "auto_fix_safety_match",
        )
    )


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = max(len(rows), 1)
    return {
        "language_accuracy": _rate(rows, "language_match", total),
        "runtime_accuracy": _rate(rows, "runtime_match", total),
        "error_type_accuracy": _rate(rows, "error_type_match", total),
        "root_cause_keyword_match_rate": _rate(rows, "root_cause_keyword_match", total),
        "auto_fix_safety_match_rate": _rate(rows, "auto_fix_safety_match", total),
        "pass_count": sum(1 for row in rows if row.get("pass")),
    }


def _rate(rows: list[dict[str, Any]], key: str, total: int) -> float:
    return round(sum(1 for row in rows if row.get(key)) / total, 4)


def _contains_keyword(text: str, keyword: str) -> bool:
    if not keyword:
        return False
    return keyword.lower() in (text or "").lower()


def _load_expected(cases_dir: Path) -> dict[str, Any]:
    path = cases_dir / EXPECTED_FILENAME
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _command_for_case(name: str) -> str:
    commands = {
        "python_traceback.log": "python app.py",
        "django_runserver.log": "python manage.py runserver",
        "fastapi_uvicorn.log": "uvicorn main:app --reload",
        "node_stack.log": "node server.js",
        "npm_error.log": "npm run dev",
        "env_var.log": "custom-server",
        "port_conflict.log": "npm run dev",
    }
    return commands.get(name, "")


def write_reports(report: dict[str, Any]) -> None:
    JSON_REPORT.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(JSON_REPORT, json.dumps(report, indent=2))
    _atomic_write_text(MD_REPORT, _markdown_report(report))


def _atomic_write_text(path: Path, content: str) -> None:
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Watch Mode Accuracy Report",
        "",
        f"- Cases: {report['record_count']}",
        f"- Language accuracy: {report['language_accuracy']:.2%}",
        f"- Runtime accuracy: {report['runtime_accuracy']:.2%}",
        f"- Error type accuracy: {report['error_type_accuracy']:.2%}",
        f"- Root cause keyword match: {report['root_cause_keyword_match_rate']:.2%}",
        f"- Auto-fix safety match: {report['auto_fix_safety_match_rate']:.2%}",
        f"- Passed: {report['pass_count']}/{report['record_count']}",
        "",
        "| Case | Language | Runtime | Error Type | Root Keyword | Auto-fix | Pass |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["rows"]:
        lines.append(
            "| {case} | {language} | {runtime} | {error_type} | {keyword} | {auto_fix} | {passed} |".format(
                case=row["case"],
                language=_cell(row["detected_language"], row["language_match"]),
                runtime=_cell(row["detected_runtime"], row["runtime_match"]),
                error_type=_cell(row["detected_error_type"], row["error_type_match"]),
                keyword=_cell(row["expected_root_cause_keyword"], row["root_cause_keyword_match"]),
                auto_fix=_cell(str(row["auto_fix_allowed"]).lower(), row["auto_fix_safety_match"]),
                passed="PASS" if row["pass"] else "FAIL",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _cell(value: str, ok: bool) -> str:
    return f"{value}{'' if ok else ' (mismatch)'}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate GhostFix Watch Mode log diagnosis accuracy.")
    parser.add_argument("--dir", default=str(CASES_DIR), help="Directory containing watch mode .log fixtures.")
    args = parser.parse_args()
    report = evaluate_watch_mode(Path(args.dir))
    write_reports(report)
    print(
        "Watch Mode benchmark complete: "
        f"language={report['language_accuracy']:.2%}, "
        f"runtime={report['runtime_accuracy']:.2%}, "
        f"error_type={report['error_type_accuracy']:.2%}, "
        f"root_cause={report['root_cause_keyword_match_rate']:.2%}, "
        f"safety={report['auto_fix_safety_match_rate']:.2%}"
    )
    print(f"Wrote {JSON_REPORT}")
    print(f"Wrote {MD_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
