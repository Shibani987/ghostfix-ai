from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.language_diagnostics import diagnose_non_python
from core.runtime_detector import infer_runtime_profile


class RuntimeProfileV05Tests(unittest.TestCase):
    def test_common_python_framework_commands_are_inferred(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "manage.py").write_text("", encoding="utf-8")
            self.assertEqual(infer_runtime_profile("python manage.py runserver", cwd=str(root)).framework, "django")
            self.assertEqual(infer_runtime_profile("flask run", cwd=str(root)).framework, "flask")
            uvicorn = infer_runtime_profile("uvicorn main:app --host 0.0.0.0 --port 8000", cwd=str(root))
            self.assertEqual(uvicorn.framework, "fastapi")
            self.assertEqual(uvicorn.runtime, "uvicorn")

    def test_npm_dev_uses_package_json_to_infer_next_or_vite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"dev": "vite --host 0.0.0.0"}, "dependencies": {"vite": "5.0.0", "react": "18.0.0"}}),
                encoding="utf-8",
            )
            vite = infer_runtime_profile("npm run dev", cwd=str(root))
            self.assertEqual(vite.framework, "vite/react")
            self.assertEqual(vite.runtime, "vite")
            (root / "package.json").write_text(
                json.dumps({"scripts": {"dev": "next dev"}, "dependencies": {"next": "15.0.0", "react": "19.0.0"}}),
                encoding="utf-8",
            )
            next_profile = infer_runtime_profile("npm run dev", cwd=str(root))
            self.assertEqual(next_profile.framework, "next.js")

    def test_php_laravel_command_is_inferred(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = infer_runtime_profile("php artisan serve", cwd=temp_dir)
        self.assertEqual(profile.language, "php")
        self.assertEqual(profile.framework, "laravel")

    def test_vite_react_module_error_gets_framework_suggestion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"dev": "vite"}, "dependencies": {"vite": "5.0.0", "react": "18.0.0"}}),
                encoding="utf-8",
            )
            diagnostic = diagnose_non_python(
                "[plugin:vite:import-analysis] Failed to resolve import './Missing' from 'src/App.jsx'. Does the file exist?\n"
                "src/App.jsx:2:19\n",
                command="npm run dev",
                cwd=str(root),
            )
        self.assertEqual(diagnostic["framework"], "vite/react")
        self.assertEqual(diagnostic["error_type"], "ViteModuleResolutionError")
        self.assertFalse(diagnostic["auto_fix_available"])

    def test_php_parse_error_can_offer_guarded_patch_preview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "index.php"
            target.write_text("<?php\n$value = 1\necho $value;\n", encoding="utf-8")
            diagnostic = diagnose_non_python(
                f"PHP Parse error: syntax error, unexpected token \"echo\" in {target} on line 2\n",
                command="php index.php",
                cwd=str(root),
            )
        self.assertEqual(diagnostic["language"], "php")
        self.assertTrue(diagnostic["auto_fix_available"])
        self.assertIn("+$value = 1;", diagnostic["patch_preview"])


if __name__ == "__main__":
    unittest.main()
