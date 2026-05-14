from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from core.language_diagnostics import diagnose_non_python
from core.repo_engine import build_repo_snapshot, classify_failure, compute_confidence, find_exact_local_symbol
from core.root_cause_analyzer import RootCauseAnalyzer
from agent.terminal_watcher import TerminalWatcher


class RepoAwareEngineV07Tests(unittest.TestCase):
    def test_repo_snapshot_ignores_generated_and_indexes_routes(self):
        with _project() as root:
            (root / "node_modules").mkdir()
            (root / "node_modules" / "ignored.js").write_text("export const hidden = true\n", encoding="utf-8")
            api = root / "src" / "app" / "api" / "users" / "route.ts"
            api.parent.mkdir(parents=True)
            api.write_text("export async function GET() { return Response.json([]) }\n", encoding="utf-8")

            snapshot = build_repo_snapshot(root)

        self.assertIn("next.js", snapshot.frameworks)
        self.assertNotIn("node_modules/ignored.js", snapshot.source_files)
        self.assertIn("/api/users", snapshot.graph.routes["src/app/api/users/route.ts"])

    def test_react_named_import_can_be_repaired_to_default_export(self):
        with _project() as root:
            component = root / "src" / "Button.jsx"
            page = root / "src" / "Page.jsx"
            component.write_text("export default function Button() { return <button /> }\n", encoding="utf-8")
            page.write_text("import { Button } from './Button'\nexport default function Page() { return <Button /> }\n", encoding="utf-8")

            diagnostic = diagnose_non_python(
                "Attempted import error: 'Button' is not exported from './Button' (imported as 'Button').\n"
                "    at main (src/Page.jsx:1:10)\n",
                command="npm run dev",
                cwd=str(root),
            )

        self.assertTrue(diagnostic["auto_fix_available"])
        self.assertEqual(diagnostic["failure_classification"], "deterministic_safe")
        self.assertIn("import Button from './Button'", diagnostic["patch_preview"])
        self.assertIn("structured_patch_plan", diagnostic)

    def test_typescript_relative_import_graph_issue_has_exact_patch(self):
        with _project() as root:
            app = root / "src" / "main.ts"
            helper = root / "src" / "helper.ts"
            app.write_text("import { helper } from './helper'\nconsole.log(helper)\n", encoding="utf-8")
            helper.write_text("export const helper = 1\n", encoding="utf-8")

            diagnostic = diagnose_non_python(
                "Module not found: Can't resolve './helper'\n    at main (src/main.ts:1:1)\n",
                command="npm run build",
                cwd=str(root),
            )

        self.assertTrue(diagnostic["auto_fix_available"])
        self.assertIn("from './helper.ts'", diagnostic["patch_preview"])

    def test_fastapi_wrong_uvicorn_app_object_is_classified_with_framework_context(self):
        with _python_project() as root:
            app = root / "main.py"
            app.write_text("from fastapi import FastAPI\napi = FastAPI()\n", encoding="utf-8")
            traceback = textwrap.dedent(f"""
                Traceback (most recent call last):
                  File "{app}", line 1, in <module>
                    from fastapi import FastAPI
                AttributeError: module 'main' has no attribute 'app'
            """).strip()

            evidence = RootCauseAnalyzer().analyze(traceback, cwd=str(root), command="uvicorn main:app --reload")

        self.assertEqual(evidence.framework, "fastapi")
        self.assertEqual(evidence.root_cause, "fastapi_app_object_not_found")
        self.assertIn("main:app", evidence.suggested_fix)

    def test_django_startup_failure_prefers_settings_business_file(self):
        with _python_project() as root:
            (root / "manage.py").write_text("print('django')\n", encoding="utf-8")
            pkg = root / "blog"
            pkg.mkdir()
            settings = pkg / "settings.py"
            settings.write_text("INSTALLED_APPS = ['missing_app']\n", encoding="utf-8")
            traceback = textwrap.dedent("""
                Traceback (most recent call last):
                  File "C:/Python/Lib/site-packages/django/apps/registry.py", line 91, in populate
                    app_config = AppConfig.create(entry)
                ModuleNotFoundError: No module named 'missing_app'
            """).strip()

            evidence = RootCauseAnalyzer().analyze(traceback, cwd=str(root), command="python manage.py runserver")

        self.assertEqual(Path(evidence.file_path).name, "settings.py")
        self.assertEqual(evidence.root_cause, "missing_django_app_or_bad_installed_apps")

    def test_flask_template_missing_is_preview_not_secret_edit(self):
        with _python_project() as root:
            app = root / "app.py"
            app.write_text("from flask import render_template\nrender_template('shop/cart.html')\n", encoding="utf-8")
            traceback = textwrap.dedent(f"""
                Traceback (most recent call last):
                  File "{app}", line 2, in <module>
                    render_template('shop/cart.html')
                jinja2.exceptions.TemplateNotFound: shop/cart.html
            """).strip()

            evidence = RootCauseAnalyzer().analyze(traceback, cwd=str(root), command="flask run")

        self.assertEqual(evidence.root_cause, "missing_template")
        self.assertIn("templates/shop/cart.html", evidence.suggested_fix)

    def test_php_namespace_class_mismatch_stays_guided_not_auto_fixed(self):
        with _php_project() as root:
            diagnostic = diagnose_non_python(
                "PHP Fatal error:  Uncaught Error: Class \"App\\Http\\Controllers\\UsrController\" not found"
                f" in {root / 'routes' / 'web.php'}:3\n",
                command="php artisan serve",
                cwd=str(root),
            )

        self.assertFalse(diagnostic["auto_fix_available"])
        self.assertIn("namespace", diagnostic["suggested_fix"].lower())
        self.assertEqual(diagnostic["failure_classification"], "suggestion_only")

    def test_confidence_uses_validation_and_exact_matches(self):
        low = compute_confidence(parser_confidence=20)
        high = compute_confidence(
            validation_success=True,
            exact_symbol_or_file_match=True,
            rerun_success=True,
            framework_confidence=90,
            parser_confidence=90,
            stacktrace_quality=90,
        )

        self.assertLess(low, high)
        self.assertEqual(classify_failure(patch_available=True, validation_available=True, exact_match=True), "deterministic_safe")

    def test_python_exact_local_symbol_lookup(self):
        with _python_project() as root:
            (root / "helpers.py").write_text("def make_user():\n    return {}\n", encoding="utf-8")

            matches = find_exact_local_symbol(root, "make_user", suffixes={".py"})

        self.assertEqual(matches, ["helpers.py"])

    def test_python_missing_import_patch_requires_exact_local_symbol(self):
        with _python_project() as root:
            app = root / "app.py"
            app.write_text("print(make_user())\n", encoding="utf-8")
            (root / "helpers.py").write_text("def make_user():\n    return {}\n", encoding="utf-8")
            traceback = textwrap.dedent(f"""
                Traceback (most recent call last):
                  File "{app}", line 1, in <module>
                    print(make_user())
                NameError: name 'make_user' is not defined
            """).strip()
            evidence = RootCauseAnalyzer().analyze(traceback, cwd=str(root), command="python app.py")
            parsed = {"raw": traceback, "type": "NameError", "message": "name 'make_user' is not defined", "file": str(app), "line": 1}

            patch = TerminalWatcher("python app.py", cwd=str(root))._safe_patch_block(evidence, parsed, {})

        self.assertTrue(patch["available"])
        self.assertIn("from helpers import make_user", patch["patch"])


class _project:
    def __enter__(self) -> Path:
        self._temp = tempfile.TemporaryDirectory()
        root = Path(self._temp.name)
        (root / "src").mkdir()
        (root / "package.json").write_text(
            json.dumps({"scripts": {"dev": "next dev", "build": "tsc --noEmit"}, "dependencies": {"next": "15.0.0", "react": "19.0.0"}}),
            encoding="utf-8",
        )
        (root / "tsconfig.json").write_text("{}", encoding="utf-8")
        return root

    def __exit__(self, exc_type, exc, tb) -> None:
        self._temp.cleanup()


class _python_project:
    def __enter__(self) -> Path:
        self._temp = tempfile.TemporaryDirectory()
        root = Path(self._temp.name)
        (root / "requirements.txt").write_text("fastapi\nflask\ndjango\n", encoding="utf-8")
        return root

    def __exit__(self, exc_type, exc, tb) -> None:
        self._temp.cleanup()


class _php_project:
    def __enter__(self) -> Path:
        self._temp = tempfile.TemporaryDirectory()
        root = Path(self._temp.name)
        (root / "routes").mkdir()
        (root / "routes" / "web.php").write_text("<?php\nuse App\\Http\\Controllers\\UserController;\n", encoding="utf-8")
        (root / "artisan").write_text("#!/usr/bin/env php\n", encoding="utf-8")
        return root

    def __exit__(self, exc_type, exc, tb) -> None:
        self._temp.cleanup()


if __name__ == "__main__":
    unittest.main()
