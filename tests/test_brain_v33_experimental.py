import unittest
from unittest.mock import patch

from core.decision_engine import apply_safety_policy, decide_fix
from ml.ghostfix_brain_v33_predict import apply_fix_template_compatibility_guard


def _parsed(error_type: str, message: str = "") -> dict:
    return {
        "raw": f"Traceback (most recent call last):\n{error_type}: {message or error_type}",
        "type": error_type,
        "message": message or error_type,
    }


def _context(snippet: str, line: str = "") -> dict:
    return {"snippet": snippet, "line": line}


def _v33_result(error_type: str, complexity: str, safety: str, guard_applied: bool = False) -> dict:
    return {
        "brain_version": "v3.3-experimental",
        "error_type": error_type,
        "fix_template": "ensure_valid_json" if error_type == "JSONDecodeError" else "correct_syntax",
        "fix_template_text": "Brain v3.3 suggestion",
        "complexity_class": complexity,
        "auto_fix_safety": safety,
        "confidence": 99,
        "guard_applied": guard_applied,
        "guard_reasons": ["test_guard"] if guard_applied else [],
        "brain_flag_active": "GHOSTFIX_BRAIN_V33=1",
    }


class BrainV33ExperimentalTests(unittest.TestCase):
    def _patch_common(self, v33_result=None, v1_result=None, v2_result=None):
        return patch.multiple(
            "core.decision_engine",
            _brain_v33_decision=lambda parsed, context: v33_result,
            _brain_v2_decision=lambda parsed, context: v2_result or {
                "brain_version": "v2 experimental",
                "brain_flag_active": "GHOSTFIX_BRAIN_V2=1",
                "error_type": parsed.get("type", ""),
                "fix_template": "correct_syntax",
                "fix_template_text": "Brain v2 suggestion",
                "confidence": 85,
            },
            _brain_v1_decision=lambda parsed, context: v1_result or {
                "brain_version": "v1",
                "brain_flag_active": "none",
                "error_type": parsed.get("type", ""),
                "fix_template": "correct_syntax",
                "fix_template_text": "Brain v1 suggestion",
                "confidence": 80,
            },
            search_memory=lambda error_type, message: None,
        )

    def test_v33_disabled_by_default(self):
        with patch.dict("os.environ", {}, clear=True), self._patch_common(
            v33_result=_v33_result("SyntaxError", "unsafe_to_autofix", "not_safe")
        ):
            decision = decide_fix(_parsed("SyntaxError", "expected ':'"), _context("if value > 0", "if value > 0"))

        self.assertEqual(decision.brain_version, "v1")
        self.assertEqual(decision.brain_flag_active, "none")

    def test_v33_enabled_only_with_env_flag(self):
        with patch.dict("os.environ", {"GHOSTFIX_BRAIN_V33": "1"}, clear=True), self._patch_common(
            v33_result=_v33_result("SyntaxError", "deterministic_safe", "safe")
        ):
            decision = decide_fix(_parsed("SyntaxError", "expected ':'"), _context("if value > 0", "if value > 0"))

        self.assertEqual(decision.brain_version, "v3.3-experimental")
        self.assertEqual(decision.brain_flag_active, "GHOSTFIX_BRAIN_V33=1")
        self.assertEqual(decision.brain_type, "SyntaxError")
        self.assertEqual(decision.brain_fix_template, "correct_syntax")

    def test_v33_has_priority_over_v2_flag(self):
        with patch.dict("os.environ", {"GHOSTFIX_BRAIN_V33": "1", "GHOSTFIX_BRAIN_V2": "1"}, clear=True), self._patch_common(
            v33_result=_v33_result("SyntaxError", "deterministic_safe", "safe")
        ):
            decision = decide_fix(_parsed("SyntaxError", "expected ':'"), _context("if value > 0", "if value > 0"))

        self.assertEqual(decision.brain_version, "v3.3-experimental")
        self.assertEqual(decision.brain_flag_active, "GHOSTFIX_BRAIN_V33=1")

    def test_v33_corrects_impossible_fix_template_pairing(self):
        prediction, confidence, reasons = apply_fix_template_compatibility_guard(
            {
                "error_type": "NameError",
                "fix_template": "verify_file_path",
                "complexity_class": "needs_context_reasoning",
                "auto_fix_safety": "not_safe",
            },
            {
                "error_type": 1.0,
                "fix_template": 1.0,
                "complexity_class": 0.9,
                "auto_fix_safety": 0.9,
            },
        )

        self.assertEqual(prediction["fix_template"], "define_or_correct_name")
        self.assertLessEqual(confidence["fix_template"], 0.5)
        self.assertIn("corrected_incompatible_fix_template", reasons)

    def test_unsafe_case_never_auto_fixes(self):
        with patch.dict("os.environ", {"GHOSTFIX_BRAIN_V33": "1"}, clear=True), self._patch_common(
            v33_result=_v33_result("RuntimeError", "unsafe_to_autofix", "not_safe", True)
        ):
            decision = decide_fix(
                _parsed("RuntimeError", "dangerous operation"),
                _context("cursor.execute('DROP TABLE audit_log')", "cursor.execute('DROP TABLE audit_log')"),
            )
            decision = apply_safety_policy(decision, patch_available=True, patch_valid=True)

        self.assertEqual(decision.complexity_class, "unsafe_to_autofix")
        self.assertEqual(decision.auto_fix_safety, "not_safe")
        self.assertFalse(decision.auto_fix_available)
        self.assertEqual(decision.brain_flag_active, "GHOSTFIX_BRAIN_V33=1")

    def test_deterministic_safe_case_allowed_only_through_safety_policy(self):
        with patch.dict("os.environ", {"GHOSTFIX_BRAIN_V33": "1"}, clear=True), self._patch_common(
            v33_result=_v33_result("SyntaxError", "deterministic_safe", "safe")
        ):
            decision = decide_fix(_parsed("SyntaxError", "expected ':'"), _context("if value > 0", "if value > 0"))
            before_policy = decision.auto_fix_available
            blocked = apply_safety_policy(decision, patch_available=False, patch_valid=False)
            blocked_available = blocked.auto_fix_available
            decision.confidence = 99
            allowed = apply_safety_policy(decision, patch_available=True, patch_valid=True)

        self.assertTrue(before_policy)
        self.assertFalse(blocked_available)
        self.assertTrue(allowed.auto_fix_available)

    def test_brain_v1_still_works_by_default(self):
        with patch.dict("os.environ", {}, clear=True), self._patch_common():
            decision = decide_fix(_parsed("SyntaxError", "expected ':'"), _context("if value > 0", "if value > 0"))

        self.assertEqual(decision.brain_version, "v1")
        self.assertEqual(decision.brain_flag_active, "none")
        self.assertEqual(decision.brain_type, "SyntaxError")


if __name__ == "__main__":
    unittest.main()
