from __future__ import annotations

import tempfile
import tomllib
import unittest
import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.main import app
from core.doctor import _package_check, run_doctor


class DoctorTests(unittest.TestCase):
    def test_doctor_returns_required_checks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "ml/models").mkdir(parents=True)
            (root / "ml/models/ghostfix_brain_v1.pkl").write_text("model", encoding="utf-8")
            (root / "ml/reports").mkdir(parents=True)
            (root / "tests/manual_server_errors").mkdir(parents=True)

            checks = run_doctor(root)

        names = {check["check"] for check in checks}
        self.assertIn("Python version", names)
        self.assertIn("OS", names)
        self.assertIn("Current working directory", names)
        self.assertIn("GhostFix imports", names)
        self.assertIn("Required package: typer", names)
        self.assertIn("Required package: rich", names)
        self.assertIn("Optional package: sklearn", names)
        self.assertIn("Optional package: numpy", names)
        self.assertIn("Optional package: dotenv", names)
        self.assertIn("Optional package: supabase", names)
        self.assertIn("GhostFix local config", names)
        self.assertIn("Memory mode", names)
        self.assertIn("Brain v1 model", names)
        self.assertIn("Manual server errors", names)
        self.assertIn("Brain v4 base model", names)
        self.assertIn("Brain v4 adapter directory", names)
        self.assertIn("Brain v4 adapter compatibility", names)

    def test_missing_optional_package_warns(self):
        with patch("importlib.util.find_spec", return_value=None):
            check = _package_check("definitely_missing_optional_package")

        self.assertEqual(check["status"], "WARN")
        self.assertIn("not installed", check["details"])

    def test_missing_required_package_fails(self):
        with patch("importlib.util.find_spec", return_value=None):
            check = _package_check("definitely_missing_required_package", required=True)

        self.assertEqual(check["status"], "FAIL")
        self.assertIn("not installed", check["details"])

    def test_cli_version_flag(self):
        result = CliRunner().invoke(app, ["--version"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("GhostFix AI v0.3.0", result.output)

    def test_config_init_and_show_use_local_config(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            with _working_directory(temp_dir):
                init_result = runner.invoke(app, ["config", "init"])
                show_result = runner.invoke(app, ["config", "show"])
                path = Path(temp_dir) / ".ghostfix" / "config.json"
                config_exists = path.exists()

        self.assertEqual(init_result.exit_code, 0, init_result.output)
        self.assertEqual(show_result.exit_code, 0, show_result.output)
        self.assertTrue(config_exists)
        self.assertIn("Running in local-only mode.", init_result.output)
        self.assertIn("memory_mode", show_result.output)
        self.assertIn("local-only", show_result.output)
        self.assertIn("Running in local-only mode.", show_result.output)

    def test_invalid_config_is_blocked(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".ghostfix" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"brain_mode": "unsafe-auto", "telemetry_enabled": true}\n', encoding="utf-8")
            with _working_directory(temp_dir):
                result = runner.invoke(app, ["config", "show"])

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("Invalid config", result.output)
        self.assertIn("brain_mode must be one of", result.output)

    def test_doctor_json_mode_returns_machine_readable_checks(self):
        result = CliRunner().invoke(app, ["doctor", "--json"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('"checks"', result.output)

    def test_run_without_cloud_env_prints_local_only_mode(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ok.py"
            path.write_text("print('ok')\n", encoding="utf-8")
            with _working_directory(temp_dir), patch.dict("os.environ", {}, clear=True):
                result = runner.invoke(app, ["run", str(path)])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Running in local-only mode.", result.output)

    def test_pyproject_console_script_points_to_typer_app(self):
        data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(data["project"]["scripts"]["ghostfix"], "cli.main:app")

@contextmanager
def _working_directory(path: str):
    old_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
