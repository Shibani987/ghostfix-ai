import unittest

from core.safety_policy import evaluate_auto_fix_policy


class ProductionSafetyPolicyTests(unittest.TestCase):
    def test_unsafe_cases_never_auto_fix(self):
        for error_type in ["FileNotFoundError", "PermissionError", "RuntimeError"]:
            decision = evaluate_auto_fix_policy(
                error_type=error_type,
                complexity_class="deterministic_safe",
                confidence=0.99,
                patch_available=True,
                patch_valid=True,
            )
            self.assertFalse(decision.auto_fix_allowed)

        for complexity in ["needs_project_context", "unsafe_to_autofix"]:
            decision = evaluate_auto_fix_policy(
                error_type="JSONDecodeError",
                complexity_class=complexity,
                confidence=0.99,
                patch_available=True,
                patch_valid=True,
            )
            self.assertFalse(decision.auto_fix_allowed)

    def test_safe_cases_can_auto_fix_after_patch_validation(self):
        for error_type in ["SyntaxError", "JSONDecodeError"]:
            decision = evaluate_auto_fix_policy(
                error_type=error_type,
                complexity_class="deterministic_safe",
                confidence=0.99,
                patch_available=True,
                patch_valid=True,
                brain_auto_fix_safety="safe",
            )
            self.assertTrue(decision.auto_fix_allowed)

    def test_guard_not_safe_blocks_auto_fix(self):
        decision = evaluate_auto_fix_policy(
            error_type="JSONDecodeError",
            complexity_class="deterministic_safe",
            confidence=0.99,
            patch_available=True,
            patch_valid=True,
            brain_auto_fix_safety="not_safe",
        )
        self.assertFalse(decision.auto_fix_allowed)

    def test_confidence_threshold_respected(self):
        decision = evaluate_auto_fix_policy(
            error_type="SyntaxError",
            complexity_class="deterministic_safe",
            confidence=0.94,
            patch_available=True,
            patch_valid=True,
            brain_auto_fix_safety="safe",
        )
        self.assertFalse(decision.auto_fix_allowed)

    def test_deterministic_verified_syntax_fix_bypasses_model_confidence_gate(self):
        decision = evaluate_auto_fix_policy(
            error_type="SyntaxError",
            complexity_class="deterministic_safe",
            confidence=0.78,
            patch_available=True,
            patch_valid=True,
            brain_auto_fix_safety="safe",
            fix_kind="deterministic_verified_fix",
        )
        self.assertTrue(decision.auto_fix_allowed)
        self.assertEqual(decision.reason, "deterministic verified syntax fix")
        self.assertFalse(decision.manual_review_required)

    def test_model_suggested_fix_keeps_confidence_gate(self):
        decision = evaluate_auto_fix_policy(
            error_type="SyntaxError",
            complexity_class="deterministic_safe",
            confidence=0.78,
            patch_available=True,
            patch_valid=True,
            brain_auto_fix_safety="safe",
            fix_kind="model_suggested_fix",
        )
        self.assertFalse(decision.auto_fix_allowed)
        self.assertTrue(decision.manual_review_required)

    def test_confidence_threshold_accepts_percent_scale_input(self):
        decision = evaluate_auto_fix_policy(
            error_type="SyntaxError",
            complexity_class="deterministic_safe",
            confidence=95,
            patch_available=True,
            patch_valid=True,
            brain_auto_fix_safety="safe",
        )
        self.assertTrue(decision.auto_fix_allowed)

    def test_patch_validation_required(self):
        decision = evaluate_auto_fix_policy(
            error_type="SyntaxError",
            complexity_class="deterministic_safe",
            confidence=0.99,
            patch_available=True,
            patch_valid=False,
            brain_auto_fix_safety="safe",
        )
        self.assertFalse(decision.auto_fix_allowed)


if __name__ == "__main__":
    unittest.main()
