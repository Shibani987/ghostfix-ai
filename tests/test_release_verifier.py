from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.main import app
from core.release_verifier import _expand_globs, _missing_optional_release_tool, release_commands, run_release_verification


class ReleaseVerifierTests(unittest.TestCase):
    def test_release_verifier_command_list_matches_required_checks(self):
        names = [name for name, _ in release_commands()]

        self.assertEqual(
            names,
            [
                "unit tests",
                "doctor",
                "config show",
                "incidents",
                "daemon status",
                "run name_error",
                "watch python demo",
                "build package",
                "twine check",
            ],
        )

    def test_release_verification_collects_pass_fail(self):
        def fake_runner(command, cwd):
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        steps = run_release_verification(cwd=Path.cwd(), runner=fake_runner)

        self.assertTrue(all(step.passed for step in steps))
        self.assertEqual(len(steps), 9)

    def test_cli_verify_release_prints_summary(self):
        runner = CliRunner()

        fake_steps = [
            type("Step", (), {"name": "doctor", "passed": True, "command": ["ghostfix", "doctor"], "returncode": 0, "output": ""})()
        ]
        with patch("core.release_verifier.run_release_verification", return_value=fake_steps):
            result = runner.invoke(app, ["verify-release"], catch_exceptions=False)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("PASS", result.output)
        self.assertIn("All required local release verification checks passed", result.output)

    def test_missing_release_tool_is_optional_warning(self):
        with patch("importlib.util.find_spec", return_value=None):
            missing = _missing_optional_release_tool(["python", "-m", "build"])

        self.assertEqual(missing, "build")

    def test_missing_wheel_for_build_is_optional_warning(self):
        def fake_find_spec(name):
            return None if name == "wheel" else object()

        with patch("importlib.util.find_spec", side_effect=fake_find_spec):
            missing = _missing_optional_release_tool(["python", "-m", "build", "--no-isolation"])

        self.assertEqual(missing, "wheel")

    def test_twine_dist_glob_ignores_temporary_files(self):
        with CliRunner().isolated_filesystem():
            root = Path.cwd()
            dist = root / "dist"
            dist.mkdir()
            (dist / "ghostfix_ai-0.6.0-py3-none-any.whl").write_text("", encoding="utf-8")
            (dist / "ghostfix-ai-0.6.0.tar.gz").write_text("", encoding="utf-8")
            (dist / "tmpk2rsp5sp").write_text("", encoding="utf-8")

            expanded = _expand_globs(["python", "-m", "twine", "check", "dist/*"], root)

        self.assertIn(str(dist / "ghostfix_ai-0.6.0-py3-none-any.whl"), expanded)
        self.assertIn(str(dist / "ghostfix-ai-0.6.0.tar.gz"), expanded)
        self.assertNotIn(str(dist / "tmpk2rsp5sp"), expanded)


if __name__ == "__main__":
    unittest.main()
