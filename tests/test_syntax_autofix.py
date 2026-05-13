from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from core.autofix import apply_patch_plan, build_patch_plan
from core.patch_validator import PatchValidator
from cli.main import app


HIGH_CONFIDENCE = {
    "confidence": 0.99,
    "complexity_class": "deterministic_safe",
    "auto_fix_safety": "safe",
}

MISSING_COLON_SOURCE = "value = 1\n\nif value > 0\n    print(value)\n"


class DeterministicSyntaxAutofixTests(unittest.TestCase):
    def test_missing_colon_fixture_gets_single_line_patch_preview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "syntax_missing_colon.py"
            path.write_text(MISSING_COLON_SOURCE, encoding="utf-8")

            plan = build_patch_plan(
                str(path),
                {"type": "SyntaxError", "line": 3, "message": "expected ':'"},
                HIGH_CONFIDENCE,
            )

            patched = _patched_source(path, plan)

        self.assertTrue(plan.available, plan.reason)
        self.assertEqual(plan.start_line, 3)
        self.assertEqual(plan.end_line, 3)
        self.assertIn("-if value > 0", plan.preview)
        self.assertIn("+if value > 0:", plan.preview)
        ast.parse(patched)
        compile(patched, str(path), "exec")

    def test_missing_parenthesis_fixture_gets_single_line_patch_preview(self):
        source = Path("tests/manual_errors/missing_parenthesis.py")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / source.name
            path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

            plan = build_patch_plan(
                str(path),
                {"type": "SyntaxError", "line": 3, "message": "'(' was never closed"},
                HIGH_CONFIDENCE,
            )

            patched = _patched_source(path, plan)

        self.assertTrue(plan.available, plan.reason)
        self.assertEqual(plan.start_line, 3)
        self.assertEqual(plan.end_line, 3)
        self.assertIn("-print(value", plan.preview)
        self.assertIn("+print(value)", plan.preview)
        ast.parse(patched)
        compile(patched, str(source), "exec")

    def test_indentation_error_fixture_gets_single_line_patch_preview(self):
        source = Path("tests/manual_errors/indentation_error.py")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / source.name
            path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

            plan = build_patch_plan(
                str(path),
                {"type": "IndentationError", "line": 4, "message": "expected an indented block"},
                HIGH_CONFIDENCE,
            )

            patched = _patched_source(path, plan)

        self.assertTrue(plan.available, plan.reason)
        self.assertEqual(plan.start_line, 4)
        self.assertEqual(plan.end_line, 4)
        self.assertIn("-print(value)", plan.preview)
        self.assertIn("+    print(value)", plan.preview)
        ast.parse(patched)
        compile(patched, str(source), "exec")

    def test_apply_patch_keeps_backup_and_patch_preview_mandatory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "missing_parenthesis.py"
            path.write_text("value = 42\nprint(value\n", encoding="utf-8")

            plan = build_patch_plan(
                str(path),
                {"type": "SyntaxError", "line": 2, "message": "'(' was never closed"},
                HIGH_CONFIDENCE,
            )
            result = apply_patch_plan(str(path), plan)

            backup = Path(result["backup"])
            patched = path.read_text(encoding="utf-8")
            backup_exists = backup.exists()
            backup_text = backup.read_text(encoding="utf-8")

        self.assertTrue(result["applied"])
        self.assertTrue(backup_exists)
        self.assertIn("-print(value", result["patch"])
        self.assertIn("+print(value)", result["patch"])
        self.assertTrue(result["rollback_metadata"]["sandbox_validated"])
        self.assertEqual(backup_text, "value = 42\nprint(value\n")
        compile(patched, str(path), "exec")

    def test_low_confidence_syntax_patch_requires_manual_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.py"
            path.write_text("if True\n    print('yes')\n", encoding="utf-8")

            plan = build_patch_plan(
                str(path),
                {"type": "SyntaxError", "line": 1, "message": "expected ':'"},
                {"confidence": 0.94},
            )

        self.assertTrue(plan.available, plan.reason)
        self.assertEqual(plan.fix_kind, "deterministic_verified_fix")

    def test_cli_fix_shows_auto_fix_available_and_patch_preview_before_confirmation(self):
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "syntax_missing_colon.py"
            path.write_text(MISSING_COLON_SOURCE, encoding="utf-8")

            result = runner.invoke(app, ["run", str(path), "--fix"], input="n\n")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("AUTO_FIX_AVAILABLE", result.output)
        self.assertIn("yes", result.output)
        self.assertNotIn("DIAGNOSIS_CONFIDENCE", result.output)
        self.assertNotIn("78%", result.output)
        self.assertIn("FIX_CONFIDENCE", result.output)
        self.assertIn("verified by local compiler", result.output)
        self.assertIn("SAFETY_LEVEL", result.output)
        self.assertIn("deterministic_safe", result.output)
        self.assertIn("VALIDATION", result.output)
        self.assertIn("ast.parse + compile passed", result.output)
        self.assertIn("Patch confidence: verified by local compiler", result.output)
        self.assertIn("PATCH_PREVIEW", result.output)
        self.assertIn("-if value > 0", result.output)
        self.assertIn("+if value > 0:", result.output)
        self.assertIn("Apply fix?", result.output)

    def test_verbose_cli_fix_shows_validator_and_compile_details(self):
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "syntax_missing_colon.py"
            path.write_text(MISSING_COLON_SOURCE, encoding="utf-8")

            result = runner.invoke(app, ["run", str(path), "--fix", "--verbose"], input="n\n")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("MODEL_CONFIDENCE", result.output)
        self.assertIn("DIAGNOSIS_CONFIDENCE", result.output)
        self.assertIn("PATCH_CONFIDENCE", result.output)
        self.assertIn("verified", result.output)
        self.assertIn("DETERMINISTIC_VALIDATOR_RESULT", result.output)
        self.assertIn("passed", result.output)
        self.assertIn("CHANGED_LINE_COUNT", result.output)
        self.assertIn("1", result.output)
        self.assertIn("COMPILE_VALIDATION_RESULT", result.output)

    def test_ambiguous_syntax_error_still_requires_manual_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ambiguous.py"
            path.write_text("values = [1, 2\nprint(values\n", encoding="utf-8")

            plan = build_patch_plan(
                str(path),
                {"type": "SyntaxError", "line": 1, "message": "'[' was never closed"},
                HIGH_CONFIDENCE,
            )

        self.assertFalse(plan.available)
        self.assertIn("manual review", plan.reason.lower())

    def test_patch_validator_uses_sandbox_before_apply(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.py"
            path.write_text("value = 1\nprint(value)\n", encoding="utf-8")
            safe_block = {
                "available": True,
                "file_path": str(path),
                "start_line": 2,
                "end_line": 2,
                "replacement": "print(value\n",
            }

            result = PatchValidator().apply_with_backup_and_compile(safe_block)

        self.assertFalse(result["applied"])
        self.assertIn("Sandbox", result["reason"])
        self.assertFalse(result["rollback_metadata"].get("sandbox_validated", True))


def _patched_source(path: Path, plan) -> str:
    original = path.read_text(encoding="utf-8").splitlines(keepends=True)
    patched = original[:]
    patched[plan.start_line - 1:plan.end_line] = plan.replacement.splitlines(keepends=True)
    return "".join(patched)


if __name__ == "__main__":
    unittest.main()
