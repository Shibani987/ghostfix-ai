from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from core.project_context import detect_project_root, scan_project_context


class ProjectContextCliTests(unittest.TestCase):
    def test_project_root_detection_uses_nearest_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "app" / "views"
            nested.mkdir(parents=True)
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            file_path = nested / "handler.py"
            file_path.write_text("print('ok')\n", encoding="utf-8")

            detected = detect_project_root(file_path, cwd=root)

        self.assertEqual(detected, root)

    def test_framework_detection_for_python_and_node_projects(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "pyproject.toml").write_text("[project]\ndependencies=['fastapi','uvicorn']\n", encoding="utf-8")
            (root / "package.json").write_text('{"dependencies":{"next":"latest","vite":"latest"}}', encoding="utf-8")
            (root / "vite.config.ts").write_text("export default {}\n", encoding="utf-8")
            app_file = root / "main.py"
            app_file.write_text("from fastapi import FastAPI\n", encoding="utf-8")

            context = scan_project_context(str(root), command="uvicorn main:app", start_path=str(app_file))

        self.assertEqual(context.framework, "fastapi")
        self.assertIn("fastapi", context.frameworks)
        self.assertIn("node", context.frameworks)
        self.assertIn("vite", context.frameworks)
        self.assertIn("pyproject.toml", context.dependency_files)
        self.assertIn("package.json", context.dependency_files)

    def test_context_command_outputs_repo_summary(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "requirements.txt").write_text("flask\n", encoding="utf-8")
            app_file = root / "app.py"
            app_file.write_text("from flask import Flask\n", encoding="utf-8")
            with _working_directory(root):
                result = runner.invoke(app, ["context", "app.py"], catch_exceptions=False)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("project root", result.output)
        self.assertIn("flask", result.output)
        self.assertIn("requirements.txt", result.output)

    def test_secret_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            (root / ".env").write_text("SECRET_KEY=real\n", encoding="utf-8")
            (root / "secrets.py").write_text("TOKEN='real'\n", encoding="utf-8")
            app_file = root / "app.py"
            app_file.write_text("print('ok')\n", encoding="utf-8")

            context = scan_project_context(str(root), start_path=str(app_file))

        self.assertNotIn(".env", context.files)
        self.assertNotIn("secrets.py", context.files)
        self.assertNotIn("real", "\n".join(context.files.values()))

    def test_context_budget_truncates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_file = root / "app.py"
            app_file.write_text("x = 1\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("x" * 1000, encoding="utf-8")

            context = scan_project_context(str(root), start_path=str(app_file), max_total_chars=40)

        self.assertTrue(context.truncated)
        self.assertLessEqual(context.total_chars, 80)


@contextmanager
def _working_directory(path: Path):
    old_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
