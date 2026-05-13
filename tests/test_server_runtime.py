from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.terminal_watcher import TerminalWatcher, TracebackBlockDetector
from core.decision_engine import decide_fix
from core.parser import parse_error
from core.project_context import scan_project_context
from core.root_cause_analyzer import RootCauseAnalyzer


class ServerRuntimeSupportTests(unittest.TestCase):
    def test_detector_captures_complete_django_traceback_block(self):
        captured = []
        detector = TracebackBlockDetector(captured.append)
        lines = [
            "Watching for file changes with StatReloader\n",
            "Traceback (most recent call last):\n",
            "  File \"manage.py\", line 22, in <module>\n",
            "    main()\n",
            "  File \"project/settings.py\", line 12, in <module>\n",
            "    SECRET_KEY = REQUIRED_SECRET\n",
            "django.core.exceptions.ImproperlyConfigured: SECRET_KEY is required\n",
        ]

        for line in lines:
            detector.feed(line)

        self.assertEqual(len(captured), 1)
        self.assertIn("project/settings.py", captured[0])
        self.assertIn("ImproperlyConfigured", captured[0])

    def test_parser_extracts_last_qualified_exception_name(self):
        parsed = parse_error(
            "Traceback (most recent call last):\n"
            "  File \"app.py\", line 7, in index\n"
            "    return render_template('dashboard.html')\n"
            "jinja2.exceptions.TemplateNotFound: dashboard.html\n"
        )

        self.assertEqual(parsed["type"], "TemplateNotFound")
        self.assertEqual(parsed["qualified_type"], "jinja2.exceptions.TemplateNotFound")
        self.assertEqual(parsed["message"], "dashboard.html")

    def test_duplicate_tracebacks_are_suppressed(self):
        traceback = (
            "Traceback (most recent call last):\n"
            "  File \"app.py\", line 4, in <module>\n"
            "    missing()\n"
            "NameError: name 'missing' is not defined\n"
        )
        watcher = TerminalWatcher("python app.py")

        with patch.object(watcher, "_handle_traceback") as handle:
            watcher._drain_detected([traceback, traceback])

        self.assertEqual(handle.call_count, 1)

    def test_django_traceback_uses_project_frame_and_safe_scan_skips_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "manage.py").write_text("import django\n", encoding="utf-8")
            package = root / "project"
            package.mkdir()
            (package / "settings.py").write_text("INSTALLED_APPS = []\nSECRET_KEY = REQUIRED_SECRET\n", encoding="utf-8")
            (root / ".env").write_text("SECRET_KEY=real-secret\n", encoding="utf-8")
            traceback = (
                "Traceback (most recent call last):\n"
                "  File \"C:\\Python311\\Lib\\site-packages\\django\\core\\management\\base.py\", line 1, in run\n"
                "    execute()\n"
                f"  File \"{package / 'settings.py'}\", line 2, in <module>\n"
                "    SECRET_KEY = REQUIRED_SECRET\n"
                "django.core.exceptions.ImproperlyConfigured: SECRET_KEY is required\n"
            )

            evidence = RootCauseAnalyzer().analyze(
                traceback,
                cwd=temp_dir,
                command="python manage.py runserver",
            )
            project_context = scan_project_context(temp_dir, "python manage.py runserver")

        self.assertEqual(evidence.framework, "django")
        self.assertTrue(evidence.file_path.endswith("settings.py"))
        self.assertEqual(evidence.line_number, 2)
        self.assertNotIn(".env", project_context.files)
        self.assertNotIn("real-secret", "\n".join(project_context.files.values()))
        self.assertNotIn("REQUIRED_SECRET", "\n".join(project_context.files.values()))
        self.assertEqual(evidence.root_cause, "django_configuration_error")
        self.assertEqual(evidence.source, "framework_rule")

    def test_flask_traceback_gets_framework_diagnosis(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "requirements.txt").write_text("Flask==3.0.0\n", encoding="utf-8")
            (root / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\nmissing()\n", encoding="utf-8")
            traceback = (
                "Traceback (most recent call last):\n"
                "  File \"app.py\", line 3, in <module>\n"
                "    missing()\n"
                "NameError: name 'missing' is not defined\n"
            )

            evidence = RootCauseAnalyzer().analyze(traceback, cwd=temp_dir, command="flask run")

        self.assertEqual(evidence.framework, "flask")
        self.assertIn("missing", evidence.failing_line)
        self.assertTrue(evidence.evidence)

    def test_flask_template_not_found_is_not_labeled_django(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            django_fixture = root / "django_fixture" / "project"
            django_fixture.mkdir(parents=True)
            (django_fixture / "settings.py").write_text("INSTALLED_APPS = []\n", encoding="utf-8")
            flask_root = root / "flask_app"
            flask_root.mkdir()
            (flask_root / "app.py").write_text(
                "from flask import Flask, render_template\n"
                "app = Flask(__name__)\n"
                "@app.get('/')\n"
                "def index():\n"
                "    return render_template('dashboard.html')\n",
                encoding="utf-8",
            )
            traceback = (
                "Traceback (most recent call last):\n"
                f"  File \"{flask_root / 'app.py'}\", line 5, in index\n"
                "    return render_template('dashboard.html')\n"
                "  File \"C:\\Python311\\Lib\\site-packages\\jinja2\\environment.py\", line 1, in get_template\n"
                "    raise TemplateNotFound(template)\n"
                "jinja2.exceptions.TemplateNotFound: dashboard.html\n"
            )

            evidence = RootCauseAnalyzer().analyze(traceback, cwd=temp_dir, command="python flask_app/app.py")
            project_context = scan_project_context(temp_dir, "python flask_app/app.py", str(flask_root / "app.py"))

        self.assertEqual(evidence.error_type, "TemplateNotFound")
        self.assertEqual(evidence.framework, "flask")
        self.assertEqual(evidence.root_cause, "missing_template")
        self.assertNotIn("missing_template", evidence.likely_root_cause)
        self.assertIn("Flask could not find", evidence.likely_root_cause)
        self.assertEqual(evidence.source, "framework_rule")
        self.assertIn("`templates/dashboard.html`", evidence.suggested_fix)
        self.assertNotIn("django_fixture/project/settings.py", project_context.files)

    def test_fastapi_uvicorn_import_traceback_gets_framework_diagnosis(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "pyproject.toml").write_text('dependencies = ["fastapi", "uvicorn"]\n', encoding="utf-8")
            (root / "main.py").write_text("from fastapi import FastAPI\nfrom missing_pkg import tool\napp = FastAPI()\n", encoding="utf-8")
            traceback = (
                "Traceback (most recent call last):\n"
                "  File \"main.py\", line 2, in <module>\n"
                "    from missing_pkg import tool\n"
                "ModuleNotFoundError: No module named 'missing_pkg'\n"
            )

            evidence = RootCauseAnalyzer().analyze(traceback, cwd=temp_dir, command="uvicorn main:app --reload")

        self.assertEqual(evidence.framework, "fastapi")
        self.assertEqual(evidence.error_type, "ModuleNotFoundError")
        self.assertEqual(evidence.root_cause, "fastapi_app_import_error")
        self.assertNotIn("fastapi_app_import_error", evidence.likely_root_cause)
        self.assertIn("FastAPI failed while Uvicorn was importing the app", evidence.likely_root_cause)
        self.assertIn("missing_pkg", evidence.likely_root_cause)
        self.assertIn("missing_pkg", evidence.suggested_fix)
        self.assertIn("Uvicorn module:app target", evidence.suggested_fix)
        self.assertIn("startup import", evidence.suggested_fix)
        self.assertEqual(evidence.source, "framework_rule")

    def test_django_installed_apps_module_error_has_specific_root_cause(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "manage.py").write_text("import django\n", encoding="utf-8")
            package = root / "project"
            package.mkdir()
            (package / "settings.py").write_text("INSTALLED_APPS = ['missing_inventory_app']\n", encoding="utf-8")
            traceback = (
                "Traceback (most recent call last):\n"
                "  File \"manage.py\", line 22, in <module>\n"
                "    execute_from_command_line(sys.argv)\n"
                "  File \"C:\\Python311\\Lib\\site-packages\\django\\apps\\registry.py\", line 91, in populate\n"
                "    app_config = AppConfig.create(entry)\n"
                f"  File \"{package / 'settings.py'}\", line 1, in <module>\n"
                "    INSTALLED_APPS = ['missing_inventory_app']\n"
                "ModuleNotFoundError: No module named 'missing_inventory_app'\n"
            )

            evidence = RootCauseAnalyzer().analyze(traceback, cwd=temp_dir, command="python manage.py runserver")

        self.assertEqual(evidence.framework, "django")
        self.assertEqual(evidence.root_cause, "missing_django_app_or_bad_installed_apps")
        self.assertNotIn("missing_django_app_or_bad_installed_apps", evidence.likely_root_cause)
        self.assertIn("INSTALLED_APPS", evidence.likely_root_cause)
        self.assertIn("missing_inventory_app", evidence.suggested_fix)
        self.assertTrue(any("apps.populate" in item or "settings" in item for item in evidence.evidence))

    def test_django_installed_apps_error_anchors_frozen_importlib_to_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "manage.py").write_text("import django\n", encoding="utf-8")
            package = root / "project"
            package.mkdir()
            (package / "settings.py").write_text("INSTALLED_APPS = ['missing_inventory_app']\n", encoding="utf-8")
            traceback = (
                "Traceback (most recent call last):\n"
                "  File \"C:\\Python311\\Lib\\site-packages\\django\\apps\\registry.py\", line 91, in populate\n"
                "    app_config = AppConfig.create(entry)\n"
                "  File \"<frozen importlib._bootstrap>\", line 1140, in _find_and_load_unlocked\n"
                "ModuleNotFoundError: No module named 'missing_inventory_app'\n"
            )

            evidence = RootCauseAnalyzer().analyze(traceback, cwd=temp_dir, command="python manage.py runserver")

        self.assertEqual(evidence.framework, "django")
        self.assertTrue(evidence.file_path.endswith("settings.py"))
        self.assertEqual(evidence.failing_line, "INSTALLED_APPS = ['missing_inventory_app']")
        self.assertEqual(evidence.root_cause, "missing_django_app_or_bad_installed_apps")

    def test_django_settings_already_configured_rule(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "django_bad_settings.py"
            path.write_text(
                "from django.conf import settings\n"
                "settings.configure(DEBUG=True)\n"
                "settings.configure(DEBUG=False)\n",
                encoding="utf-8",
            )
            traceback = (
                "Traceback (most recent call last):\n"
                f"  File \"{path}\", line 3, in <module>\n"
                "    settings.configure(DEBUG=False)\n"
                "RuntimeError: Settings already configured.\n"
            )

            evidence = RootCauseAnalyzer().analyze(traceback, cwd=temp_dir, command=f"python {path.name}")

        self.assertEqual(evidence.framework, "django")
        self.assertEqual(evidence.root_cause, "django_settings_already_configured")
        self.assertNotIn("django_settings_already_configured", evidence.likely_root_cause)
        self.assertIn("configured more than once", evidence.likely_root_cause)
        self.assertIn("duplicate settings.configure", evidence.suggested_fix)

    def test_all_framework_root_causes_have_human_readable_explanations(self):
        labels = {
            "missing_template",
            "flask_app_context_error",
            "missing_django_app_or_bad_installed_apps",
            "django_settings_already_configured",
            "django_configuration_error",
            "missing_django_template",
            "fastapi_app_import_error",
            "fastapi_app_object_not_found",
        }
        analyzer = RootCauseAnalyzer()
        for label in labels:
            with self.subTest(label=label):
                evidence = type("Evidence", (), {})()
                evidence.source = "framework_rule"
                evidence.root_cause = label
                evidence.error_message = "dashboard.html" if "template" in label else "No module named 'missing_pkg'"
                evidence.line_number = 5
                evidence.failing_line = "from missing_pkg import tool"
                explanation = analyzer._human_root_cause(evidence)

                self.assertNotEqual(explanation, label)
                self.assertNotIn(label, explanation)

    def test_low_confidence_conflicting_brain_prediction_is_suppressed(self):
        parsed = {"raw": "Traceback\nRuntimeError: Settings already configured.", "type": "RuntimeError", "message": "Settings already configured."}
        with patch.dict("os.environ", {}, clear=True), patch.multiple(
            "core.decision_engine",
            search_memory=lambda error_type, message: None,
            _retriever_decision=lambda parsed_error, context: None,
            _brain_v1_decision=lambda parsed_error, context: {
                "brain_version": "v1",
                "brain_flag_active": "none",
                "error_type": "KeyError",
                "fix_template": "check_key",
                "confidence": 0.42,
            },
        ):
            decision = decide_fix(parsed, {})

        self.assertEqual(decision.brain_type, "")
        self.assertEqual(decision.brain_fix_template, "")
        self.assertIn("ignored", decision.brain_ignored_reason)


if __name__ == "__main__":
    unittest.main()
