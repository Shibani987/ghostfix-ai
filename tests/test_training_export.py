from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from core.feedback import save_feedback
from core.fix_audit import record_fix_audit
from core.incidents import incidents_path, make_incident, record_incident
from core.training_export import sanitize_text


class TrainingExportTests(unittest.TestCase):
    def test_export_file_creation(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "app.py"
            target.write_text("print('x')\n", encoding="utf-8")
            record_incident(
                make_incident(
                    command="python app.py",
                    file=str(target),
                    language="python",
                    runtime="django",
                    error_type="NameError",
                    cause="missing variable",
                    fix="define the variable",
                    confidence=88,
                    auto_fix_available=False,
                    resolved_after_fix=False,
                ),
                root=root,
            )
            save_feedback("good", note="clear", root=root)
            record_fix_audit(
                target_file=str(target),
                validator_result="blocked by safety policy",
                rollback_available=False,
                user_confirmed=False,
                root=root,
            )

            result = _invoke_in(root, runner, ["export-training-data"])
            exports = list((root / ".ghostfix" / "exports").glob("ghostfix_training_export_*.jsonl"))
            rows = _read_jsonl(exports[0])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Export created locally.", result.output)
        self.assertIn("No data was uploaded.", result.output)
        self.assertIn("Review before sharing.", result.output)
        self.assertEqual(len(exports), 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["error_type"], "NameError")
        self.assertEqual(rows[0]["framework"], "django")
        self.assertEqual(rows[0]["feedback_rating"], "good")
        self.assertEqual(rows[0]["validator_result"], "blocked by safety policy")
        self.assertEqual(set(rows[0]), {
            "error_type",
            "framework",
            "runtime",
            "language",
            "likely_cause",
            "suggested_fix",
            "confidence",
            "auto_fix_available",
            "rollback_available",
            "resolved_after_fix",
            "feedback_rating",
            "feedback_note",
            "validator_result",
        })

    def test_export_works_with_missing_local_files(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = _invoke_in(root, runner, ["export-training-data"])
            exports = list((root / ".ghostfix" / "exports").glob("ghostfix_training_export_*.jsonl"))
            rows = _read_jsonl(exports[0])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("EXPORT_ROWS: 0", result.output)
        self.assertEqual(len(exports), 1)
        self.assertEqual(rows, [])

    def test_redaction_behavior(self):
        raw = (
            r"C:\Users\Shibani\project\app.py "
            "/home/alice/project/app.py "
            "alice@example.com "
            "API_KEY=sk_test_abcdefghijklmnopqrstuvwxyz123456 "
            "SECRET_VALUE=super-private "
            "-----BEGIN PRIVATE KEY-----abc123-----END PRIVATE KEY----- "
            "password=my-password"
        )

        redacted = sanitize_text(raw)

        self.assertNotIn("Shibani", redacted)
        self.assertNotIn("/home/alice", redacted)
        self.assertNotIn("alice@example.com", redacted)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", redacted)
        self.assertNotIn("super-private", redacted)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("my-password", redacted)
        self.assertIn("<HOME_PATH>", redacted)
        self.assertIn("<EMAIL>", redacted)
        self.assertIn("<REDACTED>", redacted)

    def test_include_snippets_warning_and_sanitized_short_snippet(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = incidents_path(root)
            path.parent.mkdir(parents=True, exist_ok=True)
            row = {
                "timestamp": "2026-05-12T10:00:00",
                "command": "python app.py",
                "file": r"C:\Users\Alice\project\app.py",
                "language": "python",
                "runtime": "python",
                "error_type": "ValueError",
                "cause": "bad value",
                "fix": "validate input",
                "confidence": 91,
                "auto_fix_available": False,
                "resolved_after_fix": False,
                "rollback_metadata": {},
                "snippet": "TOKEN=super-secret\nprint('short')",
            }
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")

            result = _invoke_in(root, runner, ["export-training-data", "--include-snippets"])
            exports = list((root / ".ghostfix" / "exports").glob("ghostfix_training_export_*.jsonl"))
            rows = _read_jsonl(exports[0])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Snippets may contain project code. Review before sharing.", result.output)
        self.assertIn("snippet", rows[0])
        self.assertNotIn("super-secret", rows[0]["snippet"])
        self.assertIn("<REDACTED>", rows[0]["snippet"])

    def test_stats_command_output(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "app.py"
            target.write_text("print('x')\n", encoding="utf-8")
            record_incident(
                make_incident(
                    command="python app.py",
                    file=str(target),
                    language="python",
                    runtime="flask",
                    error_type="SyntaxError",
                    cause="missing colon",
                    fix="add colon",
                    confidence=99,
                    auto_fix_available=True,
                    resolved_after_fix=True,
                    rollback_metadata={"backup": str(root / "app.py.bak"), "target": str(target)},
                ),
                root=root,
            )
            save_feedback("bad", note="wrong fix", root=root)
            record_fix_audit(
                target_file=str(target),
                patch="+:",
                validator_result="dry-run; patch not applied",
                rollback_available=False,
                user_confirmed=False,
                root=root,
            )
            record_fix_audit(
                target_file=str(target),
                backup_path=str(root / "app.py.bak"),
                patch="rollback restore",
                validator_result="rollback completed",
                rollback_available=True,
                user_confirmed=True,
                root=root,
            )

            result = _invoke_in(root, runner, ["stats"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("TOTAL_INCIDENTS: 1", result.output)
        self.assertIn("TOTAL_SUCCESSFUL_DIAGNOSES: 1", result.output)
        self.assertIn("TOTAL_AUTO_FIX_ATTEMPTS: 2", result.output)
        self.assertIn("TOTAL_ROLLBACK_EVENTS: 1", result.output)
        self.assertIn("FEEDBACK_BAD: 1", result.output)
        self.assertIn("DRY_RUN_USAGE_COUNT: 1", result.output)
        self.assertIn("GhostFix Local Stats", result.output)


def _invoke_in(root: Path, runner: CliRunner, args: list[str]):
    old_cwd = Path.cwd()
    os.chdir(root)
    try:
        return runner.invoke(app, args, catch_exceptions=False)
    finally:
        os.chdir(old_cwd)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
