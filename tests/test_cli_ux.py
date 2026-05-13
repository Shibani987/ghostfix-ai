from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from core.incidents import make_incident, record_incident


class CliUxTests(unittest.TestCase):
    def test_run_output_has_plain_summary_and_no_code_changed(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fail.py"
            path.write_text("missing_name\n", encoding="utf-8")

            result = runner.invoke(app, ["run", str(path)], catch_exceptions=False)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("STATUS:", result.output)
        self.assertIn("ERROR:", result.output)
        self.assertIn("ROOT_CAUSE:", result.output)
        self.assertIn("NEXT_STEP:", result.output)
        self.assertIn("Next step:", result.output)
        self.assertIn("AUTO_FIX:", result.output)
        self.assertIn("Auto-fix available: no", result.output)
        self.assertIn("ROLLBACK_AVAILABLE:", result.output)
        self.assertIn("Rollback available: no", result.output)
        self.assertIn("No code was changed", result.output)

    def test_fix_decline_output_says_no_code_changed_and_auto_fix_available(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.py"
            path.write_text("if True\n    print('yes')\n", encoding="utf-8")

            result = runner.invoke(app, ["run", str(path), "--fix"], input="n\n", catch_exceptions=False)
            text_after = path.read_text(encoding="utf-8")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Next step:", result.output)
        self.assertIn("Auto-fix available: yes", result.output)
        self.assertIn("Rollback available: no", result.output)
        self.assertIn("No code was changed", result.output)
        self.assertEqual(text_after, "if True\n    print('yes')\n")

    def test_rollback_output_reports_availability(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "app.py"
            backup = root / "app.py.bak"
            target.write_text("patched\n", encoding="utf-8")
            backup.write_text("original\n", encoding="utf-8")
            record_incident(
                make_incident(
                    command="python app.py",
                    file=str(target),
                    language="python",
                    runtime="python",
                    error_type="SyntaxError",
                    cause="missing colon",
                    fix="add colon",
                    confidence=99,
                    auto_fix_available=True,
                    resolved_after_fix=False,
                    rollback_metadata={"backup": str(backup), "target": str(target), "sandbox_validated": True},
                ),
                root=root,
            )

            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                result = runner.invoke(app, ["rollback", "last"], input="n\n", catch_exceptions=False)
            finally:
                os.chdir(old_cwd)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("ROLLBACK_AVAILABLE: yes", result.output)
        self.assertIn("Rollback available: yes", result.output)
        self.assertIn("Next step:", result.output)
        self.assertIn("No code was changed", result.output)

    def test_feedback_output_has_next_step(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                result = runner.invoke(app, ["feedback", "--good"], catch_exceptions=False)
            finally:
                os.chdir(old_cwd)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Feedback saved locally.", result.output)
        self.assertIn("STATUS: feedback saved", result.output)
        self.assertIn("Next step:", result.output)

    def test_doctor_output_has_plain_summary(self):
        result = CliRunner().invoke(app, ["doctor"], catch_exceptions=False)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("STATUS:", result.output)
        self.assertIn("ROOT_CAUSE: environment check", result.output)
        self.assertIn("Next step:", result.output)
        self.assertIn("Auto-fix available: no", result.output)
        self.assertIn("Rollback available: no", result.output)

    def test_dry_run_missing_file_explains_no_modification_and_examples(self):
        result = CliRunner().invoke(app, ["run", "definitely_missing_app.py", "--dry-run"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("DRY_RUN: enabled", result.output)
        self.assertIn("No code will be modified", result.output)
        self.assertIn("STATUS: blocked", result.output)
        self.assertIn("ERROR: file not found", result.output)
        self.assertIn("NEXT_STEP: run `ghostfix examples` or try an existing Python file", result.output)
        self.assertIn("No code was changed.", result.output)

    def test_doctor_marks_optional_warnings_as_non_blocking(self):
        result = CliRunner().invoke(app, ["doctor"], catch_exceptions=False)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("REQUIRED CHECKS:", result.output)
        self.assertIn("OPTIONAL CHECKS:", result.output)
        self.assertIn("Optional warnings do not block local Python diagnosis.", result.output)
        self.assertIn("Brain v4 is optional and not required for daily local use.", result.output)


if __name__ == "__main__":
    unittest.main()
