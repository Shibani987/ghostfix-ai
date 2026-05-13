from __future__ import annotations

import unittest
import os
import tempfile
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app


class OnboardingCliTests(unittest.TestCase):
    def test_quickstart_command_shows_install_and_daily_workflow(self):
        result = CliRunner().invoke(app, ["quickstart"], catch_exceptions=False)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("GhostFix quickstart", result.output)
        self.assertIn("Install verification:", result.output)
        self.assertIn("ghostfix doctor", result.output)
        self.assertIn("Zero-config start:", result.output)
        self.assertIn("ghostfix setup", result.output)
        self.assertIn("ghostfix run app.py", result.output)
        self.assertIn('ghostfix watch "python manage.py runserver"', result.output)
        self.assertIn("First safe demos:", result.output)
        self.assertIn("ghostfix run tests/manual_errors/name_error.py --dry-run", result.output)
        self.assertIn('ghostfix watch "python demos/python_name_error.py" --dry-run', result.output)
        self.assertIn("ghostfix demo", result.output)
        self.assertIn("Trust commands:", result.output)
        self.assertIn("ghostfix rollback last", result.output)
        self.assertIn("Watch examples:", result.output)
        self.assertIn(".ghostfix/incidents.jsonl", result.output)
        self.assertIn(".ghostfix/feedback.jsonl", result.output)
        self.assertIn(".ghostfix/reports/", result.output)

    def test_examples_command_shows_categorized_examples(self):
        result = CliRunner().invoke(app, ["examples"], catch_exceptions=False)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Copy-paste friendly command examples.", result.output)
        for heading in ["Python script:", "Django:", "FastAPI:", "Flask:", "Node:", "Rollback:", "Feedback:"]:
            with self.subTest(heading=heading):
                self.assertIn(heading, result.output)
        self.assertIn('ghostfix watch "npm run dev"', result.output)
        self.assertIn('ghostfix feedback --bad --note "wrong root cause"', result.output)

    def test_doctor_onboarding_wording_is_clear_and_local_first(self):
        result = CliRunner().invoke(app, ["doctor"], catch_exceptions=False)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("ONBOARDING:", result.output)
        self.assertIn("local-only mode", result.output)
        self.assertIn("Brain optionality", result.output)
        self.assertIn("safety policy", result.output)
        self.assertIn("rollback support", result.output)
        self.assertIn(".ghostfix/incidents.jsonl", result.output)
        self.assertIn(".ghostfix/feedback.jsonl", result.output)
        self.assertIn("ghostfix quickstart", result.output)

    def test_onboarding_docs_and_readme_sections_exist(self):
        quickstart = Path("docs/QUICKSTART.md").read_text(encoding="utf-8")
        examples = Path("docs/EXAMPLES.md").read_text(encoding="utf-8")
        readme = Path("README.md").read_text(encoding="utf-8")

        self.assertIn("# GhostFix Quickstart", quickstart)
        self.assertIn("ghostfix doctor", quickstart)
        self.assertIn("ghostfix rollback last", quickstart)
        self.assertIn("ghostfix run tests/manual_errors/name_error.py --dry-run", readme)
        self.assertNotIn("ghostfix run app.py --dry-run", readme)
        self.assertIn("# GhostFix Examples", examples)
        self.assertIn("## Node", examples)
        self.assertIn("## 2 Minute Quickstart", readme)
        self.assertIn("## Daily-Driver Beta Limitations", readme)
        self.assertIn("## Safety Guarantees", readme)
        self.assertIn("## What GhostFix Will Never Do", readme)
        self.assertIn("## Local-First Promise", readme)

    def test_setup_creates_local_first_config(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            old_cwd = Path.cwd()
            os.chdir(temp_dir)
            try:
                result = runner.invoke(app, ["setup"], catch_exceptions=False)
                config_path = Path(temp_dir) / ".ghostfix" / "config.json"
                config = config_path.read_text(encoding="utf-8")
            finally:
                os.chdir(old_cwd)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("GhostFix is ready", result.output)
        self.assertIn("LOCAL_FIRST: yes", result.output)
        self.assertIn("NO_API_KEY_REQUIRED: yes", result.output)
        self.assertIn('"brain_mode": "off"', config)
        self.assertIn('"telemetry_enabled": false', config)

    def test_demo_command_is_short_safe_and_reproducible(self):
        result = CliRunner().invoke(app, ["demo"], catch_exceptions=False)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Demo Flow", result.output)
        self.assertIn("DEMO_COMMAND:", result.output)
        self.assertIn("DRY_RUN: enabled", result.output)
        self.assertIn("No code was modified", result.output)
        self.assertIn("STATUS: demo complete", result.output)


if __name__ == "__main__":
    unittest.main()
