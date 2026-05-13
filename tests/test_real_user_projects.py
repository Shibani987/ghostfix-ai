from __future__ import annotations

import unittest
from pathlib import Path


class RealUserProjectFixtureTests(unittest.TestCase):
    def test_real_user_project_fixtures_exist(self):
        root = Path("tests/real_user_projects")
        expected = [
            "django_blog/manage.py",
            "django_blog/blog/settings.py",
            "django_blog/blog/settings_import_failure.py",
            "fastapi_api/main.py",
            "fastapi_api/bad_app.py",
            "fastapi_api/env_app.py",
            "flask_shop/app.py",
            "flask_shop/templates/shop/cart.html",
            "simple_script/name_error.py",
            "simple_script/file_not_found.py",
            "simple_script/json_decode.py",
            "node_express/package.json",
            "node_express/server.js",
        ]

        for relative_path in expected:
            with self.subTest(relative_path=relative_path):
                self.assertTrue((root / relative_path).exists())

    def test_real_world_results_document_lists_scenarios(self):
        text = Path("docs/REAL_WORLD_RESULTS.md").read_text(encoding="utf-8")
        required_phrases = [
            "# GhostFix Real World Results",
            "| Project | Runtime | Error | Command | Useful? | Correct? | Crash? | Wrong Fix? | Notes |",
            "missing app / bad INSTALLED_APPS",
            "missing settings import",
            "missing template",
            "missing dependency import",
            "bad app import/startup",
            "missing environment variable",
            "TemplateNotFound",
            "route/runtime exception",
            "NameError",
            "FileNotFoundError",
            "JSONDecodeError",
            "missing module",
            "bad env var",
            "startup crash",
            'ghostfix watch "python manage.py runserver"',
            'ghostfix watch "uvicorn main:app --reload"',
            'ghostfix watch "python app.py"',
            'ghostfix watch "npm run dev"',
            "ghostfix run tests/real_user_projects/simple_script/name_error.py",
        ]

        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
