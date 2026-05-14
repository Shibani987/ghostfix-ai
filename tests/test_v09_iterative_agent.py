from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.iterative_agent import iterative_validate_patch
from core.patch_validator import PatchValidator


class IterativeAgentV09Tests(unittest.TestCase):
    def test_nextjs_iterative_import_fix_converges(self):
        with _ts_project() as root:
            app = root / "src" / "app.ts"
            helper = root / "src" / "helper.ts"
            app.write_text("import { helper } from './helper'\nconst value = 1\nconsole.log(helper, value)\n", encoding="utf-8")
            helper.write_text("export const helper = 1;\n", encoding="utf-8")
            seed = _line_patch(app, 2, "const value = 1;\n", framework="next.js")
            with patch("subprocess.run", side_effect=[_fail("Error: Cannot find module './helper'\n    at main (src/app.ts:1:1)\n"), _ok(), _ok(), _ok()]):
                result = iterative_validate_patch(_diag(app, "next.js"), seed, command="npm run build", cwd=str(root))

        self.assertTrue(result.ok, result.reason)
        self.assertEqual(len(result.telemetry), 2)
        self.assertIn("from './helper.ts'", result.patch_block["patch"])
        self.assertTrue(result.rollback_verified)

    def test_react_export_mismatch_retry_converges(self):
        with _ts_project(framework="react") as root:
            app = root / "src" / "App.tsx"
            button = root / "src" / "Button.tsx"
            app.write_text("import { Button } from './Button'\nconst value = 1\nexport default function App() { return value }\n", encoding="utf-8")
            button.write_text("export default function Button() { return null }\n", encoding="utf-8")
            seed = _line_patch(app, 2, "const value = 1;\n", framework="react")
            failure = "Attempted import error: 'Button' is not exported from './Button'\n    at main (src/App.tsx:1:1)\n"
            with patch("subprocess.run", side_effect=[_fail(failure), _ok(), _ok(), _ok()]):
                result = iterative_validate_patch(_diag(app, "react"), seed, command="npm run build", cwd=str(root))

        self.assertTrue(result.ok, result.reason)
        self.assertIn("import Button from './Button'", result.patch_block["patch"])
        self.assertGreaterEqual(result.confidence, 80)

    def test_fastapi_wrong_app_object_rerun_validates(self):
        with _python_project() as root:
            main = root / "main.py"
            main.write_text("from fastapi import FastAPI\napi = FastAPI()\n", encoding="utf-8")
            seed = _line_patch(main, 2, "app = FastAPI()\n", language="python", framework="fastapi")
            with patch("subprocess.run", return_value=_ok()):
                result = iterative_validate_patch(_diag(main, "fastapi", language="python"), seed, command="uvicorn main:app --reload", cwd=str(root))

        self.assertTrue(result.ok, result.reason)
        self.assertIn("app = FastAPI()", result.patch_block["patch"])
        self.assertEqual(result.patch_block["language"], "python")

    def test_django_import_retry_validates(self):
        with _python_project() as root:
            views = root / "views.py"
            views.write_text("from .urls import urlpatterns\nROUTE = 'old'\n", encoding="utf-8")
            seed = _line_patch(views, 2, "ROUTE = 'blog/'\n", language="python", framework="django")
            with patch("subprocess.run", return_value=_ok()):
                result = iterative_validate_patch(_diag(views, "django", language="python"), seed, command="python manage.py runserver", cwd=str(root))

        self.assertTrue(result.ok, result.reason)
        self.assertIn("ROUTE = 'blog/'", result.patch_block["patch"])

    def test_typescript_compile_fix_rerun_validates(self):
        with _ts_project(framework="typescript") as root:
            index = root / "src" / "index.ts"
            index.write_text("const name: string = 1;\n", encoding="utf-8")
            seed = _line_patch(index, 1, "const name: string = '1';\n", framework="typescript")
            with patch("subprocess.run", return_value=_ok()):
                result = iterative_validate_patch(_diag(index, "typescript"), seed, command="tsc --noEmit", cwd=str(root))

        self.assertTrue(result.ok, result.reason)
        self.assertIn("const name: string = '1';", result.patch_block["patch"])

    def test_regression_detection_stops_retry_loop(self):
        with _ts_project() as root:
            app = root / "src" / "app.ts"
            app.write_text("const value = 1\n", encoding="utf-8")
            seed = _line_patch(app, 1, "const value = 1;\n", framework="next.js")
            failure = "Error: Missing required environment variable NEXT_PUBLIC_API_URL\n"
            with patch("subprocess.run", return_value=_fail(failure)):
                result = iterative_validate_patch(_diag(app, "next.js", confidence=95), seed, command="npm run build", cwd=str(root))

        self.assertFalse(result.ok)
        self.assertTrue(result.regression_detected)
        self.assertTrue(result.telemetry[-1].regression_detected)

    def test_framework_apply_creates_rollback_metadata_for_recovery(self):
        with _ts_project() as root:
            app = root / "src" / "app.ts"
            app.write_text("const value = 1\n", encoding="utf-8")
            seed = _line_patch(app, 1, "const value = 1;\n", framework="next.js")
            with patch("subprocess.run", return_value=_ok()):
                result = iterative_validate_patch(_diag(app, "next.js"), seed, command="npm run build", cwd=str(root))
                applied = PatchValidator().apply_with_backup_and_compile(result.patch_block)

            self.assertTrue(applied["applied"], applied)
            backup_rows = applied["rollback_metadata"]["backups"]
            self.assertTrue(backup_rows)
            backup_path = Path(backup_rows[0]["backup"])
            target_path = Path(backup_rows[0]["target"])
            target_path.write_text(backup_path.read_text(encoding="utf-8"), encoding="utf-8")
            self.assertEqual(target_path.read_text(encoding="utf-8"), "const value = 1\n")


class _ts_project:
    def __init__(self, framework: str = "next.js"):
        self.framework = framework

    def __enter__(self) -> Path:
        self._temp = tempfile.TemporaryDirectory()
        root = Path(self._temp.name)
        deps = {"typescript": "5.0.0"}
        if self.framework == "next.js":
            deps.update({"next": "15.0.0", "react": "19.0.0"})
        elif self.framework == "react":
            deps.update({"react": "19.0.0", "vite": "6.0.0"})
        (root / "package.json").write_text(json.dumps({"scripts": {"build": "tsc --noEmit"}, "dependencies": deps}), encoding="utf-8")
        (root / "tsconfig.json").write_text("{}", encoding="utf-8")
        (root / "src").mkdir()
        return root

    def __exit__(self, exc_type, exc, tb) -> None:
        self._temp.cleanup()


class _python_project:
    def __enter__(self) -> Path:
        self._temp = tempfile.TemporaryDirectory()
        root = Path(self._temp.name)
        (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
        (root / "manage.py").write_text("print('django')\n", encoding="utf-8")
        return root

    def __exit__(self, exc_type, exc, tb) -> None:
        self._temp.cleanup()


def _line_patch(path: Path, line: int, replacement: str, *, language: str = "javascript/typescript", framework: str = "typescript") -> dict:
    old_lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines = old_lines[:]
    new_lines[line - 1:line] = [replacement]
    import difflib

    return {
        "available": True,
        "file_path": str(path),
        "start_line": line,
        "end_line": line,
        "replacement": replacement,
        "patch": "".join(difflib.unified_diff(old_lines, new_lines, fromfile=str(path), tofile=str(path), lineterm="\n")),
        "language": language,
        "framework": framework,
    }


def _diag(path: Path, framework: str, *, language: str = "javascript/node", confidence: int = 85) -> dict:
    return {
        "language": language,
        "framework": framework,
        "file": str(path),
        "error_type": "BuildSyntaxError",
        "root_cause": "next_build_syntax_error",
        "message": "initial deterministic failure",
        "confidence": confidence,
    }


def _ok() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["validation"], 0, stdout="ok\n", stderr="")


def _fail(text: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["validation"], 1, stdout="", stderr=text)


if __name__ == "__main__":
    unittest.main()
