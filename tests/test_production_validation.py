from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from agent.daemon_runtime import start_daemon
from cli.main import app
from core.incidents import load_incidents, make_incident, record_incident
from core.log_events import LogEventKind, LogEventPipeline
from core.parser import extract_runtime_error, parse_error
from core.production_validator import production_commands, run_production_validation


class ProductionValidationStressTests(unittest.TestCase):
    def test_stress_huge_logs_do_not_exceed_buffers(self):
        pipeline = LogEventPipeline(max_buffer_size=4096, max_event_size=1024)

        events = pipeline.feed(("noise" * 50_000) + "\n")

        self.assertLessEqual(len(pipeline.buffered_text()), 4096)
        self.assertTrue(events[0].truncated)

    def test_stress_unicode_logs_do_not_crash_parser(self):
        pipeline = LogEventPipeline()

        events = pipeline.feed("starting 🚀\nTraceback (most recent call last):\n".encode("utf-8"))
        events.extend(pipeline.feed("  File \"app.py\", line 1, in <module>\nValueError: café broke\n"))

        self.assertTrue(any(event.kind == LogEventKind.PYTHON_TRACEBACK for event in events))
        parsed = parse_error("ValueError: café broke\n")
        self.assertEqual(parsed["type"], "ValueError")

    def test_stress_partial_traceback_extracts_on_flush(self):
        pipeline = LogEventPipeline()

        pipeline.feed("Traceback (most recent call last):\n  File \"app.py\", line 1, in <module>\n")
        pipeline.feed("    boom\nRuntime")
        pipeline.feed("Error: split")
        events = pipeline.flush()

        self.assertEqual(events[-1].kind, LogEventKind.PYTHON_TRACEBACK)
        self.assertIn("RuntimeError: split", events[-1].text)

    def test_stress_repeated_errors_are_detected_without_parser_crash(self):
        output = (
            "Traceback (most recent call last):\n"
            "  File \"app.py\", line 1, in <module>\n"
            "NameError: name 'x' is not defined\n"
        ) * 50

        extracted = extract_runtime_error(output, command="python app.py")

        self.assertEqual(extracted["type"], "NameError")

    def test_stress_malformed_logs_return_safe_fallback(self):
        self.assertIsNone(extract_runtime_error(object(), command="python app.py"))
        parsed = parse_error(object())
        self.assertEqual(parsed["type"], "UnknownError")

    def test_daemon_duplicate_suppression_for_repeated_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "fail.py"
            script.write_text("missing_value\n", encoding="utf-8")
            command = f'"{sys.executable}" "{script}"'

            with redirect_stdout(StringIO()):
                start_daemon(command, cwd=str(root), restart_delay=0, max_runs=2)

            rows = load_incidents(root)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["error_type"], "NameError")

    def test_incident_history_integrity_with_rollback_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            incident = make_incident(
                command="python app.py",
                file="app.py",
                language="python",
                runtime="python",
                error_type="SyntaxError",
                cause="missing colon",
                fix="add colon",
                confidence=99,
                auto_fix_available=True,
                resolved_after_fix=True,
                rollback_metadata={"backup": "app.py.bak_20260509_120000", "sandbox_validated": True},
            )

            record_incident(incident, root=root)
            row = load_incidents(root)[0]

        self.assertEqual(set(row).issuperset({"timestamp", "command", "file", "language", "runtime", "error_type", "cause", "fix", "confidence", "auto_fix_available", "resolved_after_fix", "rollback_metadata"}), True)
        self.assertTrue(row["rollback_metadata"]["sandbox_validated"])


class ProductionValidationCommandTests(unittest.TestCase):
    def test_production_command_list_matches_required_validation(self):
        names = [name for name, _ in production_commands()]

        self.assertEqual(
            names,
            [
                "verify-release",
                "doctor",
                "config show",
                "context",
                "run name_error",
                "watch python demo",
                "watch benchmark",
                "runtime brain route-only",
            ],
        )

    def test_run_production_validation_writes_reports_and_metrics(self):
        def fake_runner(command, cwd):
            cmd = " ".join(command)
            if "evaluate_watch_mode.py" in cmd:
                reports = cwd / "ml" / "reports"
                reports.mkdir(parents=True, exist_ok=True)
                (reports / "watch_mode_eval_report.json").write_text(
                    json.dumps({"language_accuracy": 1.0, "runtime_accuracy": 1.0, "error_type_accuracy": 1.0, "root_cause_keyword_match_rate": 1.0, "auto_fix_safety_match_rate": 1.0, "pass_count": 1, "record_count": 1, "rows": [{"auto_fix_allowed": False}]}),
                    encoding="utf-8",
                )
            if "evaluate_runtime_brain_v4.py" in cmd:
                reports = cwd / "ml" / "reports"
                reports.mkdir(parents=True, exist_ok=True)
                (reports / "runtime_brain_v4_report.json").write_text(
                    json.dumps({"record_count": 1, "deterministic_solve_rate": 1.0, "unresolved_rate": 0.0, "unresolved_count": 0, "brain_activation_rate": 0.0, "brain_escalation_rate": 0.0, "rows": [{"auto_fix_available": False}]}),
                    encoding="utf-8",
                )
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = run_production_validation(cwd=root, runner=fake_runner)

            json_report = root / ".ghostfix" / "reports" / "production_validation.json"
            md_report = root / ".ghostfix" / "reports" / "production_validation.md"
            json_exists = json_report.exists()
            md_exists = md_report.exists()

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["unsafe_fix_rate"], 0.0)
        self.assertEqual(report["unresolved_rate"], 0.0)
        self.assertTrue(json_exists)
        self.assertTrue(md_exists)

    def test_cli_validate_production_prints_summary(self):
        runner = CliRunner()
        fake_report = {
            "tests_passed": True,
            "cli_commands_passed": True,
            "unresolved_rate": 0.0,
            "unsafe_fix_rate": 0.0,
            "release_blockers": [],
            "reports": {
                "json": ".ghostfix/reports/production_validation.json",
                "markdown": ".ghostfix/reports/production_validation.md",
            },
            "steps": [
                {"name": "doctor", "passed": True},
            ],
        }

        with patch("core.production_validator.run_production_validation", return_value=fake_report):
            result = runner.invoke(app, ["validate-production"], catch_exceptions=False)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Local release validation passed", result.output)
        self.assertIn("doctor", result.output)


if __name__ == "__main__":
    unittest.main()
