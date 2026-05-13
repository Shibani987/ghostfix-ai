from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.autofix import build_patch_plan
from core.confidence import confidence_percent, normalize_confidence
from core.decision_engine import apply_safety_policy, decide_fix, format_decision
from core.formatter import format_compact_decision
from core.runner import run_command


class RuntimeQualityTests(unittest.TestCase):
    def test_confidence_normalization_and_display(self):
        self.assertEqual(normalize_confidence(95), 0.95)
        self.assertEqual(normalize_confidence(0.92), 0.92)
        self.assertEqual(confidence_percent(0.95), 95)

        decision = decide_fix(
            {"raw": "Traceback\nSyntaxError: expected ':'", "type": "SyntaxError", "message": "expected ':'"},
            {"line": "def login(user)"},
        )
        self.assertLessEqual(decision.confidence, 1.0)
        formatted = format_decision(decision)
        self.assertIn("DIAGNOSIS_CONFIDENCE:\n95%", formatted)
        self.assertIn("MODEL_CONFIDENCE:\n95%", formatted)

    def test_compact_display_hides_brain_telemetry(self):
        decision = decide_fix(
            {"raw": "Traceback\nAttributeError: 'NoneType' object has no attribute 'email'", "type": "AttributeError", "message": "'NoneType' object has no attribute 'email'"},
            {"line": "print(user.email)"},
        )
        compact = format_compact_decision(decision)

        self.assertIn("ERROR_TYPE:\nAttributeError", compact)
        self.assertIn("CAUSE:", compact)
        self.assertIn("FIX:", compact)
        self.assertIn("CONFIDENCE:", compact)
        self.assertIn("AUTO_FIX_AVAILABLE:", compact)
        self.assertNotIn("BRAIN_USED", compact)
        self.assertNotIn("DECISION_SOURCE_PATH", compact)
        self.assertNotIn("AUTO_FIX_PLAN", compact)

    def test_safety_policy_allows_normalized_threshold_value(self):
        decision = decide_fix(
            {"raw": "Traceback\nSyntaxError: expected ':'", "type": "SyntaxError", "message": "expected ':'"},
            {"line": "def login(user)"},
        )
        decision.confidence = 0.95
        decision.complexity_class = "deterministic_safe"
        decision.auto_fix_safety = "safe"

        allowed = apply_safety_policy(decision, patch_available=True, patch_valid=True)

        self.assertTrue(allowed.auto_fix_available)

    def test_no_duplicate_panel_output_for_waiting_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad_json.py"
            path.write_text("import json\ndata = ''\nresult = json.loads(data)\n", encoding="utf-8")

            with patch("core.runner.show_output") as show_output, patch("core.runner.Confirm.ask", return_value=False):
                run_command(str(path), auto_fix=True, max_loops=1)

        self.assertEqual(show_output.call_count, 1)
        autofix = show_output.call_args.args[0]["autofix"]
        self.assertEqual(autofix["reason"], "waiting for confirmation")

    def test_jsondecodeerror_patch_preview_has_clean_lines_and_valid_python(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad_json.py"
            path.write_text("import json\ndata = ''\nresult = json.loads(data)", encoding="utf-8")
            parsed = {
                "type": "JSONDecodeError",
                "line": 3,
                "message": "Expecting value: line 1 column 1 (char 0)",
            }

            plan = build_patch_plan(str(path), parsed, {})
            original = path.read_text(encoding="utf-8").splitlines(keepends=True)
            patched = original[:]
            patched[plan.start_line - 1:plan.end_line] = plan.replacement.splitlines(keepends=True)

        self.assertTrue(plan.available, plan.reason)
        self.assertNotIn(")+if", plan.preview)
        self.assertNotIn("data)+", plan.preview)
        ast.parse("".join(patched))

    def test_syntaxerror_missing_colon_wording_distinguishes_function_and_class(self):
        function_decision = decide_fix(
            {"raw": "Traceback\nSyntaxError: expected ':'", "type": "SyntaxError", "message": "expected ':'"},
            {"line": "def login(user)"},
        )
        class_decision = decide_fix(
            {"raw": "Traceback\nSyntaxError: expected ':'", "type": "SyntaxError", "message": "expected ':'"},
            {"line": "class User"},
        )

        self.assertEqual(function_decision.cause, "The function definition is missing a colon.")
        self.assertEqual(class_decision.cause, "The class definition is missing a colon.")


if __name__ == "__main__":
    unittest.main()
