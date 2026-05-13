from __future__ import annotations

import sys
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from agent.terminal_watcher import TerminalWatcher
from cli.main import app


class WatchCliSmokeTests(unittest.TestCase):
    def test_watch_failing_python_script_diagnoses_without_fix_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script = Path(temp_dir) / "fail.py"
            script.write_text("missing_name\n", encoding="utf-8")
            command = f'"{sys.executable}" "{script}"'
            watcher = TerminalWatcher(command, cwd=temp_dir, auto_fix=False, verbose=False)

            with patch("rich.prompt.Confirm.ask", side_effect=AssertionError("must not prompt")), redirect_stdout(StringIO()) as output:
                result = watcher.watch()

        self.assertNotEqual(result.returncode, 0)
        text = output.getvalue()
        self.assertIn("NameError", text)
        self.assertIn("GhostFix Brain", text)
        self.assertIn("Watch mode diagnosis only", text)

    def test_cli_watch_smoke_uses_command_argument(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            script = Path(temp_dir) / "fail.py"
            script.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
            command = f'"{sys.executable}" "{script}"'

            result = runner.invoke(app, ["watch", command, "--no-brain"], catch_exceptions=False)

        self.assertNotEqual(result.exit_code, 2)
        self.assertIn("RuntimeError", result.output)
        self.assertIn("GhostFix Brain", result.output)

    def test_node_watch_diagnosis_never_autofixes(self):
        watcher = TerminalWatcher("npm run dev", auto_fix=False, verbose=False)
        diagnostic = watcher._runtime_diagnostic(
            {
                "language": "javascript/node",
                "type": "ReferenceError",
                "message": "missingValue is not defined",
                "kind": "node_stack",
            },
            "ReferenceError: missingValue is not defined\n    at main (server.js:1:1)\n",
        )

        self.assertEqual(diagnostic["language"], "javascript/node")
        self.assertFalse(diagnostic["auto_fix_available"])

    def test_uvicorn_command_not_found_watch_diagnosis(self):
        watcher = TerminalWatcher("uvicorn main:app --reload", auto_fix=False, verbose=False)
        diagnostic = watcher._runtime_diagnostic(
            {
                "language": "unknown",
                "type": "CommandNotFoundError",
                "message": "'uvicorn' is not recognized as an internal or external command",
                "framework": "fastapi",
                "kind": "command_not_found",
            },
            "'uvicorn' is not recognized as an internal or external command\n",
        )

        self.assertEqual(diagnostic["error_type"], "CommandNotFoundError")
        self.assertIn("not installed", diagnostic["likely_root_cause"])
        self.assertIn("python -m uvicorn", diagnostic["suggested_fix"])

    def test_demo_fixture_commands_exist(self):
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "demos/python_name_error.py").exists())
        self.assertTrue((root / "demos/django_like/manage.py").exists())
        self.assertTrue((root / "demos/fastapi_like/main.py").exists())
        self.assertTrue((root / "demos/node_like/package.json").exists())
        self.assertTrue((root / "demos/node_like/server.js").exists())

    def test_watch_mode_can_diagnose_python_demo_fixture(self):
        root = Path(__file__).resolve().parents[1]
        command = f'"{sys.executable}" "demos/python_name_error.py"'
        watcher = TerminalWatcher(command, cwd=str(root), auto_fix=False, verbose=False)

        with redirect_stdout(StringIO()) as output:
            result = watcher.watch()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NameError", output.getvalue())

    def test_watch_mode_can_diagnose_django_like_demo_fixture(self):
        root = Path(__file__).resolve().parents[1]
        command = f'"{sys.executable}" "demos/django_like/manage.py" runserver'
        watcher = TerminalWatcher(command, cwd=str(root), auto_fix=False, verbose=False)

        with redirect_stdout(StringIO()) as output:
            result = watcher.watch()

        self.assertNotEqual(result.returncode, 0)
        text = output.getvalue()
        self.assertIn("ImproperlyConfigured", text)
        self.assertIn("Django", text)

    def test_watch_mode_can_diagnose_fastapi_like_demo_fixture(self):
        root = Path(__file__).resolve().parents[1]
        command = f'"{sys.executable}" "demos/fastapi_like/main.py"'
        watcher = TerminalWatcher(command, cwd=str(root), auto_fix=False, verbose=False)

        with redirect_stdout(StringIO()) as output:
            result = watcher.watch()

        self.assertNotEqual(result.returncode, 0)
        text = output.getvalue()
        self.assertIn("ModuleNotFoundError", text)
        self.assertIn("FastAPI", text)

    @unittest.skipUnless(shutil.which("npm"), "npm is not installed")
    def test_watch_mode_can_diagnose_node_like_demo_fixture(self):
        root = Path(__file__).resolve().parents[1]
        watcher = TerminalWatcher("npm run dev", cwd=str(root / "demos/node_like"), auto_fix=False, verbose=False)

        with redirect_stdout(StringIO()) as output:
            result = watcher.watch()

        self.assertNotEqual(result.returncode, 0)
        text = output.getvalue()
        self.assertIn("Cannot find module", text)
        self.assertIn("GhostFix Brain", text)


if __name__ == "__main__":
    unittest.main()
