import unittest
from unittest.mock import patch

from core.decision_engine import decide_fix
from ml.ghostfix_brain_v2_predict import apply_auto_fix_safety_guard


def _parsed(error_type: str, message: str = "") -> dict:
    return {
        "raw": f"Traceback (most recent call last):\n{error_type}: {message or error_type}",
        "type": error_type,
        "message": message or error_type,
    }


def _context(snippet: str, line: str = "") -> dict:
    return {"snippet": snippet, "line": line}


def _v2_result(error_type: str, complexity: str, safety: str, guard_applied: bool = False) -> dict:
    return {
        "brain_version": "v2 experimental",
        "error_type": error_type,
        "fix_template": "ensure_valid_json" if error_type == "JSONDecodeError" else "define_or_correct_name",
        "fix_template_text": "Brain v2 suggestion",
        "complexity_class": complexity,
        "auto_fix_safety": safety,
        "confidence": 99,
        "guard_applied": guard_applied,
    }


class BrainV2ExperimentalTests(unittest.TestCase):
    def _with_v2(self, result):
        return patch.multiple(
            "core.decision_engine",
            _brain_v2_decision=lambda parsed, context: result,
            search_memory=lambda error_type, message: None,
        )

    def test_brain_v2_jsondecode_safe_case_keeps_rule_auto_fix(self):
        with patch.dict("os.environ", {"GHOSTFIX_BRAIN_V2": "1"}, clear=True), self._with_v2(
            _v2_result("JSONDecodeError", "deterministic_safe", "safe")
        ):
            decision = decide_fix(
                _parsed("JSONDecodeError", "Expecting value: line 1 column 1 (char 0)"),
                _context("import json\nraw = ''\ndata = json.loads(raw)", "data = json.loads(raw)"),
            )

        self.assertEqual(decision.brain_version, "v2 experimental")
        self.assertEqual(decision.complexity_class, "deterministic_safe")
        self.assertEqual(decision.auto_fix_safety, "safe")
        self.assertTrue(decision.auto_fix_available)

    def test_brain_v2_nameerror_does_not_enable_auto_fix(self):
        with patch.dict("os.environ", {"GHOSTFIX_BRAIN_V2": "1"}, clear=True), self._with_v2(
            _v2_result("NameError", "needs_context_reasoning", "not_safe", True)
        ):
            decision = decide_fix(
                _parsed("NameError", "name 'foo' is not defined"),
                _context("print(foo)", "print(foo)"),
            )

        self.assertEqual(decision.brain_version, "v2 experimental")
        self.assertEqual(decision.auto_fix_safety, "not_safe")
        self.assertTrue(decision.guard_applied)
        self.assertFalse(decision.auto_fix_available)

    def test_brain_v2_filenotfound_does_not_enable_auto_fix(self):
        with patch.dict("os.environ", {"GHOSTFIX_BRAIN_V2": "1"}, clear=True), self._with_v2(
            _v2_result("FileNotFoundError", "needs_project_context", "not_safe", True)
        ):
            decision = decide_fix(
                _parsed("FileNotFoundError", "No such file or directory: 'missing.txt'"),
                _context("Path('missing.txt').read_text()", "Path('missing.txt').read_text()"),
            )

        self.assertIn(decision.complexity_class, [
    "needs_project_context",
    "needs_context_reasoning",
])
        self.assertEqual(decision.auto_fix_safety, "not_safe")
        self.assertFalse(decision.auto_fix_available)

    def test_brain_v2_unsafe_to_autofix_forces_no_auto_fix(self):
        with patch.dict("os.environ", {"GHOSTFIX_BRAIN_V2": "1"}, clear=True), self._with_v2(
            _v2_result("TypeError", "unsafe_to_autofix", "not_safe", True)
        ):
            decision = decide_fix(
                _parsed("TypeError", "expected str, bytes or os.PathLike object, not NoneType"),
                _context("subprocess.run(command, shell=True)", "subprocess.run(command, shell=True)"),
            )

        self.assertEqual(decision.complexity_class, "unsafe_to_autofix")
        self.assertEqual(decision.auto_fix_safety, "not_safe")
        self.assertFalse(decision.auto_fix_available)

    def test_brain_v2_guard_blocks_unsafe_to_autofix_even_if_raw_safe(self):
        raw = {
            "error_type": "TypeError",
            "fix_template": "check_type_or_signature",
            "complexity": "unsafe_to_autofix",
            "auto_fix_safety": "safe",
        }
        guarded, reasons = apply_auto_fix_safety_guard(
            raw,
            {"auto_fix_safety": 0.99},
            "TypeError: expected str\nsubprocess.run(command, shell=True)",
            "subprocess.run(command, shell=True)",
        )

        self.assertEqual(guarded, "not_safe")
        self.assertIn("blocked_complexity", reasons)


if __name__ == "__main__":
    unittest.main()
