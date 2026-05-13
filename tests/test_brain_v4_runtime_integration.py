from __future__ import annotations

import unittest
import tempfile
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from core.decision_engine import apply_safety_policy, decide_fix
from core.runner import run_command
from ml.evaluate_runtime_brain_v4 import evaluate_runtime_cases
from ml.brain_v4_inference import BRAIN_V4_SCHEMA_KEYS


def _parsed(error_type: str, message: str = "") -> dict:
    return {
        "raw": f"Traceback (most recent call last):\n{error_type}: {message or error_type}",
        "type": error_type,
        "message": message or error_type,
    }


def _context(snippet: str, line: str = "") -> dict:
    return {"snippet": snippet, "line": line}


def _diagnosis(error_type: str = "TypeError", *, safe_to_autofix: bool = False) -> dict:
    return {
        "language": "python",
        "framework": "python",
        "error_type": error_type,
        "root_cause": "brain_v4_root_cause",
        "likely_root_cause": "Brain v4 found the likely cause.",
        "evidence": ["Traceback contains the target error."],
        "suggested_fix": "Review and apply the targeted code change.",
        "confidence": 91,
        "safe_to_autofix": safe_to_autofix,
    }


class _UnavailableBrainV4:
    def diagnose(self, **kwargs):
        return {"available": False, "reason": "LoRA adapter path does not exist: missing"}


class _AvailableBrainV4:
    def __init__(self, diagnosis: dict):
        self.diagnosis = diagnosis

    def diagnose(self, **kwargs):
        return {"available": True, "diagnosis": self.diagnosis}


class _EchoBrainV4:
    def diagnose(self, **kwargs):
        parsed_error = kwargs.get("parsed_error") or {}
        diagnosis = _diagnosis(parsed_error.get("type") or "CustomError", safe_to_autofix=False)
        if kwargs.get("include_debug"):
            return {
                "available": True,
                "diagnosis": diagnosis,
                "prompt": "debug prompt",
                "raw_output": json.dumps(diagnosis),
                "parsed_output": diagnosis,
                "final_output": diagnosis,
            }
        return {
            "available": True,
            "diagnosis": diagnosis,
        }


class BrainV4RuntimeIntegrationTests(unittest.TestCase):
    def test_brain_v4_disabled_keeps_existing_brain_behavior(self):
        with patch.dict("os.environ", {}, clear=True), patch.multiple(
            "core.decision_engine",
            search_memory=lambda error_type, message: None,
            _retriever_decision=lambda parsed_error, context: None,
            _brain_v4_decision=lambda parsed_error, context: self.fail("Brain v4 should be disabled"),
            _brain_v1_decision=lambda parsed_error, context: {
                "brain_version": "v1",
                "brain_flag_active": "none",
                "error_type": parsed_error.get("type", ""),
                "fix_template": "legacy_brain_hint",
                "confidence": 80,
            },
        ):
            decision = decide_fix(_parsed("NameError", "name 'foo' is not defined"), _context("print(foo)", "print(foo)"))

        self.assertEqual(decision.brain_version, "v1")
        self.assertEqual(decision.brain_flag_active, "none")
        self.assertEqual(decision.brain_fix_template, "legacy_brain_hint")

    def test_missing_brain_v4_adapter_does_not_crash(self):
        with patch.dict("os.environ", {"GHOSTFIX_BRAIN_V4": "1"}, clear=True), patch.multiple(
            "core.decision_engine",
            search_memory=lambda error_type, message: None,
            _retriever_decision=lambda parsed_error, context: None,
            _brain_v4_runtime=lambda: self.fail("Brain v4 should be gated for deterministic rules"),
        ):
            decision = decide_fix(_parsed("NameError", "name 'foo' is not defined"), _context("print(foo)", "print(foo)"))

        self.assertEqual(decision.error_type, "NameError")
        self.assertEqual(decision.brain_flag_active, "GHOSTFIX_BRAIN_V4=1")
        self.assertFalse(decision.brain_used)
        self.assertEqual(decision.brain_skipped_reason, "deterministic rule matched")
        self.assertFalse(decision.auto_fix_available)

    def test_brain_v4_output_is_normalized_to_decision_format(self):
        diagnosis = _diagnosis("TypeError", safe_to_autofix=False)
        with patch.dict(
            "os.environ",
            {"GHOSTFIX_BRAIN_V4": "1", "GHOSTFIX_FORCE_BRAIN_V4": "1"},
            clear=True,
        ), patch.multiple(
            "core.decision_engine",
            search_memory=lambda error_type, message: None,
            _retriever_decision=lambda parsed_error, context: None,
            _brain_v4_runtime=lambda: _AvailableBrainV4(diagnosis),
        ):
            decision = decide_fix(_parsed("TypeError", "bad operands"), _context("x + y", "x + y"))

        self.assertEqual(decision.brain_version, "v4-lora")
        self.assertEqual(decision.brain_flag_active, "GHOSTFIX_BRAIN_V4=1")
        self.assertEqual(decision.brain_type, "TypeError")
        self.assertEqual(decision.brain_fix_template, "Review and apply the targeted code change.")
        self.assertEqual(tuple(decision.brain_v4_output), BRAIN_V4_SCHEMA_KEYS)
        self.assertEqual(decision.auto_fix_safety, "advisory_not_safe")
        self.assertTrue(decision.brain_used)

    def test_model_safe_to_autofix_does_not_bypass_runtime_safety(self):
        diagnosis = _diagnosis("TypeError", safe_to_autofix=True)
        with patch.dict(
            "os.environ",
            {"GHOSTFIX_BRAIN_V4": "1", "GHOSTFIX_FORCE_BRAIN_V4": "1"},
            clear=True,
        ), patch.multiple(
            "core.decision_engine",
            search_memory=lambda error_type, message: None,
            _retriever_decision=lambda parsed_error, context: None,
            _brain_v4_runtime=lambda: _AvailableBrainV4(diagnosis),
        ):
            decision = decide_fix(_parsed("TypeError", "bad operands"), _context("x + y", "x + y"))
            guarded = apply_safety_policy(decision, patch_available=True, patch_valid=True)

        self.assertEqual(decision.auto_fix_safety, "advisory_safe")
        self.assertFalse(guarded.auto_fix_available)
        self.assertIn("not deterministic_safe", guarded.safety_policy_reason)

    def test_malformed_generic_brain_v4_output_does_not_overwrite_rule_fix(self):
        generic = {
            "language": "unknown",
            "framework": "unknown",
            "error_type": "NameError",
            "root_cause": "unknown",
            "likely_root_cause": "unknown",
            "evidence": [],
            "suggested_fix": "Review the error and code context before changing code.",
            "confidence": 50,
            "safe_to_autofix": True,
        }
        with patch.dict(
            "os.environ",
            {"GHOSTFIX_BRAIN_V4": "1", "GHOSTFIX_FORCE_BRAIN_V4": "1"},
            clear=True,
        ), patch.multiple(
            "core.decision_engine",
            search_memory=lambda error_type, message: None,
            _retriever_decision=lambda parsed_error, context: None,
            _brain_v4_runtime=lambda: _AvailableBrainV4(generic),
        ):
            decision = decide_fix(_parsed("NameError", "name 'foo' is not defined"), _context("print(foo)", "print(foo)"))

        self.assertEqual(decision.fix, "Define the missing variable/function before using it, or fix the spelling.")
        self.assertEqual(decision.cause, "A variable or function is used before it is defined.")
        self.assertEqual(decision.brain_version, "v4-lora")
        self.assertEqual(decision.brain_fix_template, "Review the error and code context before changing code.")

    def test_normal_cli_output_has_no_brain_v4_debug_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "name_error.py"
            path.write_text("print(foo)\n", encoding="utf-8")
            with patch.dict("os.environ", {"GHOSTFIX_BRAIN_V4": "1"}, clear=True), patch.multiple(
                "core.decision_engine",
                search_memory=lambda error_type, message: None,
                _retriever_decision=lambda parsed_error, context: None,
                _brain_v4_runtime=lambda: _AvailableBrainV4(_diagnosis("NameError")),
            ), patch("core.runner.log_error"), patch("core.runner.log_decision_feedback"), redirect_stdout(StringIO()) as output:
                run_command(str(path), auto_fix=False, max_loops=1)

        text = output.getvalue()
        self.assertNotIn("RAW GENERATED CONTINUATION:", text)
        self.assertNotIn("PARSED JSON CANDIDATE:", text)
        self.assertNotIn("FINAL OUTPUT:", text)

    def test_brain_v4_runs_after_memory_rules_and_retriever(self):
        calls = []

        def search_memory(error_type, message):
            calls.append("memory")
            return None

        def rule_decision(parsed_error, context):
            calls.append("rules")
            return None

        def retriever_decision(parsed_error, context):
            calls.append("retriever")
            return None

        def brain_decision(parsed_error, context):
            calls.append("brain_v4")
            return {
                "brain_version": "v4-lora",
                "brain_flag_active": "GHOSTFIX_BRAIN_V4=1",
                "error_type": parsed_error.get("type", ""),
                "fix_template": "Brain fallback fix",
                "fix_template_text": "Brain fallback fix",
                "confidence": 91,
                "auto_fix_safety": "advisory_safe",
            }

        with patch.dict("os.environ", {"GHOSTFIX_BRAIN_V4": "1"}, clear=True), patch.multiple(
            "core.decision_engine",
            search_memory=search_memory,
            _rule_decision=rule_decision,
            _retriever_decision=retriever_decision,
            _brain_v4_decision=brain_decision,
        ):
            decide_fix(_parsed("CustomError", "custom"), _context("boom()", "boom()"))

        self.assertEqual(calls, ["memory", "rules", "retriever", "brain_v4"])

    def test_strong_rule_decision_skips_brain_v4(self):
        with patch.dict("os.environ", {"GHOSTFIX_BRAIN_V4": "1"}, clear=True), patch.multiple(
            "core.decision_engine",
            search_memory=lambda error_type, message: None,
            _retriever_decision=lambda parsed_error, context: None,
            _brain_v4_decision=lambda parsed_error, context: self.fail("Brain v4 should be skipped"),
        ):
            decision = decide_fix(
                _parsed("ZeroDivisionError", "division by zero"),
                _context("10 / 0", "10 / 0"),
            )

        self.assertFalse(decision.brain_used)
        self.assertEqual(decision.brain_skipped_reason, "deterministic rule matched")
        self.assertEqual(decision.brain_flag_active, "GHOSTFIX_BRAIN_V4=1")

    def test_low_confidence_fallback_uses_brain_v4(self):
        diagnosis = _diagnosis("CustomError", safe_to_autofix=False)
        with patch.dict("os.environ", {"GHOSTFIX_BRAIN_V4": "1"}, clear=True), patch.multiple(
            "core.decision_engine",
            search_memory=lambda error_type, message: None,
            _rule_decision=lambda parsed_error, context: None,
            _retriever_decision=lambda parsed_error, context: None,
            _brain_v4_runtime=lambda: _AvailableBrainV4(diagnosis),
        ):
            decision = decide_fix(_parsed("CustomError", "custom"), _context("boom()", "boom()"))

        self.assertTrue(decision.brain_used)
        self.assertEqual(decision.brain_version, "v4-lora")
        self.assertEqual(decision.brain_skipped_reason, "")

    def test_force_flag_runs_brain_v4_for_rule_decision(self):
        diagnosis = _diagnosis("NameError", safe_to_autofix=False)
        with patch.dict(
            "os.environ",
            {"GHOSTFIX_BRAIN_V4": "1", "GHOSTFIX_FORCE_BRAIN_V4": "1"},
            clear=True,
        ), patch.multiple(
            "core.decision_engine",
            search_memory=lambda error_type, message: None,
            _retriever_decision=lambda parsed_error, context: None,
            _brain_v4_runtime=lambda: _AvailableBrainV4(diagnosis),
        ):
            decision = decide_fix(_parsed("NameError", "name 'foo' is not defined"), _context("print(foo)", "print(foo)"))

        self.assertTrue(decision.brain_used)
        self.assertEqual(decision.brain_flag_active, "GHOSTFIX_BRAIN_V4=1")

    def test_real_world_failures_have_contextual_rule_causes(self):
        report = evaluate_runtime_cases(Path("tests/real_world_failures"), brain=True, brain_mode="auto")

        # Temporary debug output for CI
        for row in report["rows"]:
            print(f"DEBUG: {row['file']} - error_type: {row.get('detected_error_type')} - root_cause: {row.get('cause')} - decision_source_path: {row['decision_source_path']} - brain_skipped_reason: {row.get('brain_skipped_reason')} - escalation_reason: {row['escalation_reason']} - error_type_match: {row['error_type_match']}")

        self.assertEqual(report["record_count"], 10)
        self.assertEqual(report["detected_error_count"], 10)
        self.assertGreater(report["root_cause_match_rate"], 0.60)
        self.assertEqual(report["brain_used_count"], 0)
        self.assertEqual(report["brain_skipped_count"], 10)
        self.assertEqual(report["deterministic_rule_count"], 10)
        self.assertIsNotNone(report["average_deterministic_runtime_seconds"])
        for row in report["rows"]:
            self.assertFalse(row["brain_used"], row["file"])
            self.assertEqual(row["brain_skipped_reason"], "deterministic rule matched", row["file"])
            self.assertIn("rules", row["decision_source_path"], row["file"])
            self.assertEqual(row["escalation_reason"], "none", row["file"])
            self.assertTrue(row["error_type_match"], row["file"])

    def test_brain_escalation_cases_route_to_brain_with_fake_runtime(self):
        with patch.multiple(
            "core.decision_engine",
            _brain_v4_runtime=lambda: _EchoBrainV4(),
        ):
            report = evaluate_runtime_cases(Path("tests/brain_escalation_cases"), brain=True, brain_mode="auto")

        self.assertEqual(report["record_count"], 12)
        self.assertEqual(report["detected_error_count"], 12)
        self.assertEqual(report["brain_activation_count"], 12)
        self.assertEqual(report["brain_escalation_count"], 12)
        self.assertEqual(report["usable_brain_output_count"], 12)
        self.assertGreater(report["brain_escalation_rate"], 0)
        self.assertEqual(report["deterministic_solve_count"], 0)
        for row in report["rows"]:
            self.assertTrue(row["brain_escalated"], row["file"])
            self.assertTrue(row["brain_used"], row["file"])
            self.assertEqual(row["brain_failure_reason"], "success", row["file"])
            self.assertIn("brain", row["decision_source_path"], row["file"])
            self.assertIn(row["escalation_reason"], {"unsupported_error_type", "low_confidence", "missing_specific_cause"}, row["file"])

    def test_brain_mode_off_disables_brain(self):
        with patch.multiple(
            "core.decision_engine",
            _brain_v4_runtime=lambda: self.fail("Brain runtime should not be called in off mode"),
        ):
            report = evaluate_runtime_cases(Path("tests/brain_escalation_cases"), brain_mode="off", limit=1)

        row = report["rows"][0]
        self.assertEqual(report["brain_mode"], "off")
        self.assertFalse(report["brain_generation_allowed"])
        self.assertFalse(row["brain_escalated"])
        self.assertFalse(row["brain_used"])

    def test_brain_mode_route_only_records_escalation_without_generation(self):
        with patch.multiple(
            "core.decision_engine",
            _brain_v4_runtime=lambda: self.fail("Brain runtime should not be called in route-only mode"),
        ):
            report = evaluate_runtime_cases(Path("tests/brain_escalation_cases"), brain_mode="route-only", limit=1)

        row = report["rows"][0]
        self.assertEqual(report["brain_mode"], "route-only")
        self.assertFalse(report["brain_generation_allowed"])
        self.assertTrue(row["brain_escalated"])
        self.assertFalse(row["brain_used"])
        self.assertEqual(row["brain_failure_reason"], "route_only")
        self.assertIn("brain", row["decision_source_path"])

    def test_brain_mode_generate_forces_actual_brain_for_rule_case(self):
        with patch.multiple(
            "core.decision_engine",
            _brain_v4_runtime=lambda: _EchoBrainV4(),
        ):
            report = evaluate_runtime_cases(Path("tests/real_world_failures"), brain_mode="generate", limit=1)

        row = report["rows"][0]
        self.assertEqual(report["brain_mode"], "generate")
        self.assertTrue(report["brain_generation_allowed"])
        self.assertTrue(row["brain_escalated"])
        self.assertTrue(row["brain_used"])
        self.assertEqual(row["escalation_reason"], "forced_brain")

    def test_brain_debug_env_writes_artifacts(self):
        import ml.evaluate_runtime_brain_v4 as runtime_eval

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            old_json_report = runtime_eval.JSON_REPORT
            old_md_report = runtime_eval.MD_REPORT
            old_debug_dir = runtime_eval.BRAIN_DEBUG_DIR
            runtime_eval.JSON_REPORT = temp / "runtime.json"
            runtime_eval.MD_REPORT = temp / "runtime.md"
            runtime_eval.BRAIN_DEBUG_DIR = temp / "brain_debug"
            try:
                with patch.dict("os.environ", {"GHOSTFIX_SAVE_BRAIN_DEBUG": "1"}, clear=False), patch.multiple(
                    "core.decision_engine",
                    _brain_v4_runtime=lambda: _EchoBrainV4(),
                ):
                    report = evaluate_runtime_cases(Path("tests/brain_escalation_cases"), brain=True, brain_mode="auto", limit=1)
                    runtime_eval.write_reports(report)

                artifacts = list(runtime_eval.BRAIN_DEBUG_DIR.glob("*.json"))
                self.assertEqual(len(artifacts), 1)
                artifact = json.loads(artifacts[0].read_text(encoding="utf-8"))
                self.assertEqual(artifact["prompt"], "debug prompt")
                self.assertIn("raw_generation", artifact)
                self.assertIn("parsed_output", artifact)
                self.assertIn("final_normalized_output", artifact)
            finally:
                runtime_eval.JSON_REPORT = old_json_report
                runtime_eval.MD_REPORT = old_md_report
                runtime_eval.BRAIN_DEBUG_DIR = old_debug_dir


if __name__ == "__main__":
    unittest.main()
