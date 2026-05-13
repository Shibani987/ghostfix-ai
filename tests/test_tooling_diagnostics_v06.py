from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from agent.terminal_watcher import TerminalWatcher
from core.patch_validator import PatchValidator
from core.tooling_diagnostics import diagnose_tooling


class ToolingDiagnosticsV06Tests(unittest.TestCase):
    def test_missing_pnpm_is_explicit(self):
        diagnostic = diagnose_tooling("pnpm dev", cwd=".", output="pnpm: command not found\n")
        self.assertEqual(diagnostic["error_type"], "PnpmNotInstalledError")
        self.assertIn("npm install -g pnpm", diagnostic["suggested_fix"])

    def test_missing_php_is_explicit(self):
        diagnostic = diagnose_tooling("php artisan serve", cwd=".", output="'php' is not recognized as an internal or external command\n")
        self.assertEqual(diagnostic["error_type"], "PhpRuntimeMissingError")
        self.assertIn("Install PHP", diagnostic["suggested_fix"])

    def test_missing_manage_py_is_project_root_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            diagnostic = diagnose_tooling("python manage.py runserver", cwd=temp_dir)
        self.assertEqual(diagnostic["error_type"], "DjangoManagePyMissingError")
        self.assertIn("cd into the Django project", diagnostic["suggested_fix"])

    def test_missing_package_json_can_offer_minimal_create_preview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            diagnostic = diagnose_tooling("npm run dev", cwd=temp_dir)
        self.assertEqual(diagnostic["error_type"], "PackageJsonMissingError")
        self.assertTrue(diagnostic["auto_fix_available"])
        self.assertIn("+  \"scripts\"", diagnostic["patch_preview"])

    def test_missing_server_js_is_entrypoint_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            diagnostic = diagnose_tooling("node server.js", cwd=temp_dir)
        self.assertEqual(diagnostic["error_type"], "MissingEntryPointError")
        self.assertIn("server.js", diagnostic["likely_root_cause"])

    def test_missing_uvicorn_is_explicit_from_shell_output(self):
        diagnostic = diagnose_tooling("uvicorn main:app --reload", cwd=".", output="uvicorn: command not found\n")
        self.assertEqual(diagnostic["error_type"], "UvicornNotInstalledError")
        self.assertIn("pip install uvicorn", diagnostic["suggested_fix"])

    def test_missing_flask_app_discovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict("os.environ", {}, clear=True):
                diagnostic = diagnose_tooling("flask run", cwd=temp_dir)
        self.assertEqual(diagnostic["error_type"], "FlaskAppDiscoveryError")
        self.assertIn("flask --app app run", diagnostic["suggested_fix"])

    def test_missing_artisan_is_entrypoint_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            diagnostic = diagnose_tooling("php artisan serve", cwd=temp_dir)
        self.assertEqual(diagnostic["error_type"], "MissingEntryPointError")
        self.assertIn("artisan", diagnostic["likely_root_cause"])

    def test_invalid_next_root_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "package.json").write_text(json.dumps({"scripts": {"dev": "next dev"}, "dependencies": {"next": "15.0.0"}}), encoding="utf-8")
            diagnostic = diagnose_tooling("npm run dev", cwd=temp_dir)
        self.assertEqual(diagnostic["error_type"], "InvalidProjectRootError")
        self.assertIn("Next.js", diagnostic["likely_root_cause"])

    def test_watch_preflight_avoids_generic_unknown_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            watcher = TerminalWatcher("python manage.py runserver", cwd=temp_dir)
            with redirect_stdout(StringIO()) as output:
                result = watcher.watch()
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR: DjangoManagePyMissingError", output.getvalue())
        self.assertNotIn("UnknownError", output.getvalue())

    def test_create_package_json_patch_validates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            diagnostic = diagnose_tooling("npm run dev", cwd=temp_dir)
            validation = PatchValidator().validate(diagnostic["patch_block"])
        self.assertTrue(validation.ok, validation.reason)


if __name__ == "__main__":
    unittest.main()
