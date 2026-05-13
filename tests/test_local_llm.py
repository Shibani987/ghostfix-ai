from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.terminal_watcher import TerminalWatcher
from core.decision_engine import apply_safety_policy, decide_fix
from core.language_diagnostics import diagnose_non_python
from core.local_llm import diagnose_with_local_llm, parse_llm_json


class LocalLLMTests(unittest.TestCase):
    def test_no_crash_when_model_missing(self):
        with patch.dict("os.environ", {"GHOSTFIX_LOCAL_MODEL_PATH": "Z:/ghostfix/no-model-here"}, clear=False):
            result = diagnose_with_local_llm(
                language="python",
                terminal_error="Traceback\nUnknownError: bad",
                parsed_error={"type": "UnknownError", "message": "bad"},
            )

        self.assertIsNone(result)

    def test_llm_disabled_fallback_still_works(self):
        parsed = {
            "raw": "MysteryFailure: something odd happened",
            "type": "MysteryFailure",
            "message": "something odd happened",
        }
        with patch.dict("os.environ", {}, clear=True), patch("core.decision_engine.search_memory", return_value=None), patch(
            "core.decision_engine._brain_v1_decision",
            return_value=None,
        ), patch("ml.retriever_router.predict_fix", return_value=[]):
            decision = decide_fix(parsed, context="")

        self.assertEqual(decision.source, "fallback")
        self.assertFalse(decision.auto_fix_available)

    def test_malformed_llm_json_is_ignored(self):
        self.assertIsNone(parse_llm_json("not json at all"))
        self.assertIsNone(parse_llm_json('{"language": "python", "confidence": 80}'))

    def test_llm_output_never_enables_autofix(self):
        parsed = {
            "raw": "Traceback\nMysteryFailure: bad state",
            "type": "MysteryFailure",
            "message": "bad state",
        }
        llm_result = {
            "language": "python",
            "framework": "python",
            "error_type": "MysteryFailure",
            "root_cause": "mystery_failure",
            "likely_root_cause": "The local model found a likely root cause.",
            "evidence": ["terminal output contains MysteryFailure"],
            "suggested_fix": "Review the initialization path.",
            "confidence": 91,
            "safe_to_autofix": True,
        }
        with patch("core.decision_engine.search_memory", return_value=None), patch(
            "core.decision_engine._brain_v1_decision",
            return_value=None,
        ), patch("ml.retriever_router.predict_fix", return_value=[]), patch(
            "core.local_llm.diagnose_with_local_llm",
            return_value=llm_result,
        ):
            decision = decide_fix(parsed, context="")
            after_policy = apply_safety_policy(decision, patch_available=True, patch_valid=True)

        self.assertEqual(after_policy.source, "local_llm")
        self.assertFalse(after_policy.auto_fix_available)
        self.assertTrue(after_policy.manual_review_required)

    def test_non_python_autofix_remains_disabled(self):
        diagnostic = diagnose_non_python(
            "ReferenceError: missingValue is not defined\n"
            "    at Object.<anonymous> (app.js:1:1)\n",
            command="node app.js",
        )

        self.assertFalse(diagnostic["auto_fix_available"])
        self.assertEqual(diagnostic["safety_reason"], "Auto-fix is disabled for non-Python languages.")

    def test_watcher_uses_local_llm_for_unknown_terminal_output(self):
        watcher = TerminalWatcher("java Main")
        llm_diagnostic = {
            "language": "java",
            "error_type": "NullPointerException",
            "message": "boom",
            "file": "Main.java",
            "line": 8,
            "framework": "java",
            "root_cause": "java_null_pointer",
            "likely_root_cause": "A Java reference is null before use.",
            "suggested_fix": "Check the reference before dereferencing it.",
            "confidence": 79,
            "source": "local_llm",
            "auto_fix_available": False,
            "safety_reason": "Auto-fix is disabled for local LLM diagnoses.",
        }
        with patch("core.local_llm.diagnose_terminal_output", return_value=llm_diagnostic):
            result = watcher._local_llm_diagnostic("Exception in thread main\n")

        self.assertEqual(result["language"], "java")
        self.assertFalse(result["auto_fix_available"])


if __name__ == "__main__":
    unittest.main()
