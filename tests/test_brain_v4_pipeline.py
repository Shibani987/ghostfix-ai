from __future__ import annotations

import json
import importlib.util
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import ml.evaluate_brain_v4 as eval_module
import ml.evaluate_runtime_brain_v4 as runtime_eval_module
from ml import check_brain_v4_model
from ml.brain_v4_inference import (
    BrainV4Inference,
    BRAIN_V4_SCHEMA_KEYS,
    BrainV4Status,
    DEFAULT_MAX_NEW_TOKENS,
    TRAINING_SCHEMA_SYSTEM_PROMPT,
    build_generation_kwargs,
    extract_json_candidate,
    finalize_brain_v4_output,
    format_training_text,
    has_exact_brain_v4_schema,
    render_brain_v4_chat_prompt,
    parse_brain_v4_output,
)
from ml.evaluate_brain_v4 import evaluate, evaluate_predictions
from ml.train_brain_v4_lora import (
    COMMON_ERROR_TYPES,
    CausalLMPaddingCollator,
    check_training_ready,
    print_dataset_selection_debug,
    select_balanced_training_records,
    select_overfit_smoke_records,
    select_shuffled_training_records,
    tokenize_sft_record,
    tokenize_records,
)

HAS_TORCH = importlib.util.find_spec("torch") is not None


class BrainV4PipelineTests(unittest.TestCase):
    def test_training_script_reports_missing_model_cleanly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            train = temp / "train.jsonl"
            val = temp / "val.jsonl"
            train.write_text("", encoding="utf-8")
            val.write_text("", encoding="utf-8")
            config = temp / "config.yaml"
            config.write_text(
                "\n".join(
                    [
                        "base_model_path: Z:/ghostfix/no-local-model",
                        f"output_dir: {temp / 'adapter'}",
                        "data:",
                        f"  train_file: {train}",
                        f"  val_file: {val}",
                    ]
                ),
                encoding="utf-8",
            )

            readiness = check_training_ready(config)

        self.assertFalse(readiness.ready)
        self.assertIn("Base model path does not exist", readiness.reason)

    def test_evaluation_handles_missing_model_gracefully(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            val = temp / "val.jsonl"
            val.write_text(json.dumps(_record()) + "\n", encoding="utf-8")
            config = temp / "config.yaml"
            config.write_text(
                "\n".join(
                    [
                        "base_model_path: Z:/ghostfix/no-local-model",
                        f"output_dir: {temp / 'adapter'}",
                        "data:",
                        f"  val_file: {val}",
                    ]
                ),
                encoding="utf-8",
            )

            report = evaluate(config_path=config)

        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["record_count"], 1)

    def test_brain_v4_failed_load_is_not_retried_per_diagnosis(self):
        runner = BrainV4Inference()
        calls = []

        def unavailable(config=None):
            calls.append(config)
            return BrainV4Status(False, "missing local model")

        with patch("ml.brain_v4_inference.check_inference_ready", unavailable):
            first = runner.diagnose(terminal_error="NameError: missing")
            second = runner.diagnose(terminal_error="TypeError: bad")

        self.assertFalse(first["available"])
        self.assertFalse(second["available"])
        self.assertEqual(len(calls), 1)

    def test_model_checker_reports_missing_base_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            adapter = temp / "adapter"
            adapter.mkdir()
            (adapter / "adapter_config.json").write_text("{}", encoding="utf-8")
            report = check_brain_v4_model.build_report(
                temp / "missing_config.yaml",
                str(temp / "missing_base"),
                str(adapter),
            )

        self.assertFalse(report["base_model_exists"])
        self.assertTrue(report["adapter_path_exists"])
        self.assertIn("existing local base model", report["recommended_fix"])

    def test_model_checker_reports_missing_adapter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            base = temp / "base"
            base.mkdir()
            (base / "config.json").write_text('{"model_type":"qwen2","hidden_size":896}', encoding="utf-8")
            report = check_brain_v4_model.build_report(
                temp / "missing_config.yaml",
                str(base),
                str(temp / "missing_adapter"),
            )

        self.assertTrue(report["base_model_exists"])
        self.assertFalse(report["adapter_path_exists"])
        self.assertIn("LoRA adapter directory", report["recommended_fix"])

    def test_model_checker_preserves_adapter_load_exception(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            base = temp / "base"
            adapter = temp / "adapter"
            base.mkdir()
            adapter.mkdir()
            (base / "config.json").write_text('{"model_type":"qwen2","hidden_size":1536}', encoding="utf-8")
            (adapter / "adapter_config.json").write_text(
                '{"base_model_name_or_path":"training/base","target_modules":["q_proj"],"peft_version":"0.18.1"}',
                encoding="utf-8",
            )
            with patch("ml.check_brain_v4_model._try_peft_load", side_effect=RuntimeError("size mismatch q_proj")):
                report = check_brain_v4_model.build_report(temp / "missing_config.yaml", str(base), str(adapter))

        self.assertFalse(report["peft_adapter_loads"])
        self.assertIn("RuntimeError: size mismatch q_proj", report["load_exception"])
        self.assertIn("exact base model", report["recommended_fix"])

    def test_inference_load_preserves_adapter_exception_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            base = temp / "base"
            adapter = temp / "adapter"
            base.mkdir()
            adapter.mkdir()
            config = temp / "config.yaml"
            config.write_text(f"base_model_path: {base}\noutput_dir: {adapter}\n", encoding="utf-8")

            fake_torch = types.SimpleNamespace(
                cuda=types.SimpleNamespace(is_available=lambda: False),
                float16="float16",
                float32="float32",
            )
            fake_transformers = types.SimpleNamespace(
                AutoTokenizer=types.SimpleNamespace(from_pretrained=lambda *args, **kwargs: object()),
                AutoModelForCausalLM=types.SimpleNamespace(from_pretrained=lambda *args, **kwargs: object()),
            )

            class FakePeftModel:
                @staticmethod
                def from_pretrained(*args, **kwargs):
                    raise RuntimeError("size mismatch for q_proj.lora_A.default.weight")

            fake_peft = types.SimpleNamespace(PeftModel=FakePeftModel)
            with patch.dict(sys.modules, {"torch": fake_torch, "transformers": fake_transformers, "peft": fake_peft}):
                status = BrainV4Inference(config).load()

        self.assertFalse(status.available)
        self.assertIn("RuntimeError: size mismatch for q_proj", status.reason)

    def test_runtime_benchmark_limit_no_brain_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir, redirect_stdout(StringIO()) as output:
            temp = Path(temp_dir)
            (temp / "a.py").write_text("print(missing_a)\n", encoding="utf-8")
            (temp / "b.py").write_text("print(missing_b)\n", encoding="utf-8")
            report = runtime_eval_module.evaluate_runtime_cases(
                temp,
                limit=1,
                brain=False,
                timeout=5,
            )

        text = output.getvalue()
        self.assertIn("total files=1", text)
        self.assertIn("[1/1]", text)
        self.assertEqual(report["record_count"], 1)
        self.assertFalse(report["brain_enabled"])
        self.assertEqual(report["timeout_seconds"], 5)

    def test_malformed_model_output_is_rejected(self):
        self.assertIsNone(parse_brain_v4_output("this is not json"))
        parsed = parse_brain_v4_output('{"error_type": "TypeError"}')
        self.assertEqual(set(parsed), set(BRAIN_V4_SCHEMA_KEYS))
        self.assertEqual(parsed["language"], "unknown")
        self.assertEqual(parsed["framework"], "unknown")
        self.assertEqual(parsed["evidence"], [])
        self.assertEqual(parsed["confidence"], 50)

    def test_json_candidate_is_extracted_before_parsing(self):
        payload = json.dumps(_record()["output"], sort_keys=True, separators=(",", ":"))
        wrapped = f"Here is the result:\n{payload}\nDone."

        self.assertEqual(extract_json_candidate(wrapped), payload)
        self.assertEqual(parse_brain_v4_output(wrapped)["error_type"], "TypeError")
        self.assertTrue(has_exact_brain_v4_schema(parse_brain_v4_output(wrapped)))

    def test_json_candidate_is_extracted_from_fenced_output(self):
        payload = json.dumps(_record()["output"], sort_keys=True, separators=(",", ":"))
        wrapped = f"```json\n{payload}\n```"

        self.assertEqual(extract_json_candidate(wrapped), payload)
        self.assertEqual(parse_brain_v4_output(wrapped)["root_cause"], "typeerror_bad_operands")

    def test_wrong_brain_v4_keys_are_repaired_when_possible(self):
        wrong = {
            "language": "python",
            "framework": "python",
            "error_type_hint": "TypeError",
            "code_context": "x + y",
            "terminal_error": "TypeError: bad operands",
            "root_cause": "typeerror_bad_operands",
            "fix": "Convert or validate operands before adding them.",
            "confidence": 88,
        }

        parsed = parse_brain_v4_output(json.dumps(wrong))

        self.assertIsNotNone(parsed)
        self.assertEqual(set(parsed), set(_record()["output"]))
        self.assertEqual(parsed["error_type"], "TypeError")
        self.assertEqual(parsed["evidence"], ["TypeError: bad operands"])

    def test_extra_brain_v4_keys_are_removed_after_parsing(self):
        noisy = {
            **_record()["output"],
            "context": "x + y",
            "metadata": {"source": "model"},
            "error_log": "TypeError: bad",
        }

        parsed = parse_brain_v4_output(json.dumps(noisy))

        self.assertEqual(tuple(parsed), BRAIN_V4_SCHEMA_KEYS)
        self.assertNotIn("context", parsed)
        self.assertNotIn("metadata", parsed)
        self.assertNotIn("error_log", parsed)
        self.assertTrue(has_exact_brain_v4_schema(parsed))

    def test_final_brain_v4_output_rebuilds_exact_dict(self):
        noisy = {
            "language": "python",
            "framework": "python",
            "error_type": "TypeError",
            "context": "x + y",
            "metadata": {"source": "model"},
            "error_log": "TypeError: bad",
            "failing_line": "x + y",
        }

        final = finalize_brain_v4_output(noisy)

        self.assertEqual(tuple(final), BRAIN_V4_SCHEMA_KEYS)
        self.assertEqual(final["language"], "python")
        self.assertTrue(any(item.startswith("Context: x + y") for item in final["evidence"]))
        self.assertTrue(any(item.startswith("Error log: TypeError: bad") for item in final["evidence"]))
        self.assertTrue(any(item.startswith("Failing line: x + y") for item in final["evidence"]))
        self.assertEqual(final["confidence"], 50)
        for forbidden in ("context", "metadata", "error_log", "failing_line"):
            self.assertNotIn(forbidden, final)

    def test_finalizer_preserves_partial_model_fields(self):
        partial = {
            "error_type_hint": "NameError",
            "cause": "missing_variable",
            "explanation": "The variable is referenced before assignment.",
            "suggested_solution": "Define the variable before using it.",
            "context": "print(user_name)",
            "error_log": "NameError: name 'user_name' is not defined",
            "failing_line": "print(user_name)",
            "metadata": {"source": "model"},
        }

        final = finalize_brain_v4_output(partial)

        self.assertEqual(tuple(final), BRAIN_V4_SCHEMA_KEYS)
        self.assertEqual(final["error_type"], "NameError")
        self.assertEqual(final["root_cause"], "missing_variable")
        self.assertEqual(final["likely_root_cause"], "The variable is referenced before assignment.")
        self.assertEqual(final["suggested_fix"], "Define the variable before using it.")
        self.assertTrue(any(item.startswith("Context: print(user_name)") for item in final["evidence"]))
        self.assertTrue(any(item.startswith("Error log: NameError") for item in final["evidence"]))
        self.assertTrue(any(item.startswith("Failing line: print(user_name)") for item in final["evidence"]))
        for forbidden in ("context", "metadata", "error_log", "failing_line", "error_type_hint"):
            self.assertNotIn(forbidden, final)

    def test_finalizer_defaults_root_cause_from_error_type(self):
        final = finalize_brain_v4_output({"error_type": "TypeError"})

        self.assertEqual(final["error_type"], "TypeError")
        self.assertEqual(final["root_cause"], "unknown")
        self.assertEqual(final["likely_root_cause"], "unknown")
        self.assertEqual(final["suggested_fix"], "Review the error and code context before changing code.")

    def test_finalizer_infers_obvious_error_type_from_input(self):
        final = finalize_brain_v4_output({}, input_text="Traceback\nNameError: name 'user' is not defined")

        self.assertEqual(final["error_type"], "NameError")
        self.assertEqual(final["root_cause"], "unknown")
        self.assertEqual(tuple(final), BRAIN_V4_SCHEMA_KEYS)

    def test_evaluation_counts_malformed_output(self):
        metrics = evaluate_predictions([_record()], ["not json"])

        self.assertEqual(metrics["valid_json_rate"], 0.0)
        self.assertEqual(metrics["malformed_output_count"], 1)
        self.assertEqual(metrics["exact_schema_match"], 0.0)

    def test_evaluation_schema_match_uses_cleaned_output(self):
        wrong = {
            "language": "python",
            "framework": "python",
            "error_type_hint": "TypeError",
            "terminal_error": "TypeError: bad operands",
            "root_cause": "typeerror_bad_operands",
            "fix": "Convert or validate operands before adding them.",
            "confidence": 88,
        }
        metrics = evaluate_predictions([_record()], [(None, json.dumps(wrong), json.dumps(wrong))])

        self.assertEqual(metrics["valid_json_rate"], 1.0)
        self.assertEqual(metrics["exact_schema_match"], 1.0)
        self.assertEqual(metrics["schema_mismatch_count"], 0)

    def test_evaluation_normalizes_dict_prediction_with_extra_keys(self):
        noisy = {
            **_record()["output"],
            "context": "x + y",
            "metadata": {"source": "model"},
            "error_log": "TypeError: bad",
            "failing_line": "x + y",
        }
        metrics = evaluate_predictions([_record()], [noisy])

        self.assertEqual(metrics["valid_json_rate"], 1.0)
        self.assertEqual(metrics["exact_schema_match"], 1.0)
        self.assertEqual(metrics["schema_mismatch_count"], 0)

    def test_evaluation_writes_malformed_outputs_jsonl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            old_json_report = eval_module.JSON_REPORT
            old_md_report = eval_module.MD_REPORT
            old_malformed_report = eval_module.MALFORMED_REPORT
            old_schema_report = eval_module.SCHEMA_MISMATCH_REPORT
            old_debug_report = eval_module.DEBUG_GENERATIONS_REPORT
            eval_module.JSON_REPORT = temp / "brain_v4_eval_report.json"
            eval_module.MD_REPORT = temp / "brain_v4_eval_report.md"
            eval_module.MALFORMED_REPORT = temp / "malformed_outputs.jsonl"
            eval_module.SCHEMA_MISMATCH_REPORT = temp / "schema_mismatches.jsonl"
            eval_module.DEBUG_GENERATIONS_REPORT = temp / "brain_v4_debug_generations.jsonl"
            report = {
                "status": "ok",
                "reason": "",
                "validation_file": str(Path(temp_dir) / "val.jsonl"),
                "record_count": 1,
                "metrics": evaluate_predictions([_record()], ["not json"]),
                "samples": [],
                "malformed_outputs": [{"index": 0, "raw_output": "not json", "cleaned_output": ""}],
                "schema_mismatches": [{"index": 1, "wrong_keys": ["error_type_hint"]}],
                "debug_generations": [{"index": 0, "raw_model_output": "raw", "final_normalized_output": _record()["output"]}],
            }
            try:
                eval_module.write_reports(report)
                self.assertTrue(eval_module.MALFORMED_REPORT.exists())
                rows = [json.loads(line) for line in eval_module.MALFORMED_REPORT.read_text(encoding="utf-8").splitlines()]
                self.assertEqual(rows[0]["raw_output"], "not json")
                self.assertTrue(eval_module.SCHEMA_MISMATCH_REPORT.exists())
                mismatch_rows = [
                    json.loads(line)
                    for line in eval_module.SCHEMA_MISMATCH_REPORT.read_text(encoding="utf-8").splitlines()
                ]
                self.assertEqual(mismatch_rows[0]["wrong_keys"], ["error_type_hint"])
                self.assertTrue(eval_module.DEBUG_GENERATIONS_REPORT.exists())
                debug_rows = [
                    json.loads(line)
                    for line in eval_module.DEBUG_GENERATIONS_REPORT.read_text(encoding="utf-8").splitlines()
                ]
                self.assertEqual(debug_rows[0]["raw_model_output"], "raw")
            finally:
                eval_module.JSON_REPORT = old_json_report
                eval_module.MD_REPORT = old_md_report
                eval_module.MALFORMED_REPORT = old_malformed_report
                eval_module.SCHEMA_MISMATCH_REPORT = old_schema_report
                eval_module.DEBUG_GENERATIONS_REPORT = old_debug_report

    def test_inference_wrapper_never_crashes_when_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.yaml"
            config.write_text(
                "base_model_path: Z:/ghostfix/no-local-model\noutput_dir: Z:/ghostfix/no-adapter\n",
                encoding="utf-8",
            )
            runner = BrainV4Inference(config)
            result = runner.diagnose(terminal_error="TypeError: bad", context="x + y")

        self.assertFalse(result["available"])
        self.assertIn("Base model path does not exist", result["reason"])

    @unittest.skipUnless(HAS_TORCH, "Brain v4 loaded-inference smoke tests require optional torch")
    def test_loaded_inference_final_return_has_only_schema_keys(self):
        runner = BrainV4Inference()
        runner.model = _FakeModel()
        runner.tokenizer = _GeneratingTokenizer()

        with patch.dict("os.environ", {}, clear=True), redirect_stdout(StringIO()) as buffer:
            result = runner.diagnose(terminal_error="TypeError: bad", context="x + y")

        self.assertTrue(result["available"])
        self.assertIn("generation_seconds", result)
        self.assertEqual(tuple(result["diagnosis"]), BRAIN_V4_SCHEMA_KEYS)
        self.assertNotIn("raw_output", result)
        self.assertNotIn("cleaned_output", result)
        for forbidden in ("context", "metadata", "error_log", "failing_line"):
            self.assertNotIn(forbidden, result["diagnosis"])
        self.assertNotIn("RAW GENERATED CONTINUATION:", buffer.getvalue())
        self.assertNotIn("PARSED JSON CANDIDATE:", buffer.getvalue())
        self.assertNotIn("FINAL OUTPUT:", buffer.getvalue())

    @unittest.skipUnless(HAS_TORCH, "Brain v4 loaded-inference smoke tests require optional torch")
    def test_loaded_inference_debug_env_prints_raw_parsed_and_final_output(self):
        runner = BrainV4Inference()
        runner.model = _FakeModel()
        runner.tokenizer = _GeneratingTokenizer()

        with patch.dict("os.environ", {"GHOSTFIX_BRAIN_DEBUG": "1"}, clear=True), redirect_stdout(StringIO()) as buffer:
            result = runner.diagnose(terminal_error="TypeError: bad", context="x + y")

        self.assertTrue(result["available"])
        text = buffer.getvalue()
        self.assertIn("RAW GENERATED CONTINUATION:", text)
        self.assertIn("PARSED JSON CANDIDATE:", text)
        self.assertIn("FINAL OUTPUT:", text)

    @unittest.skipUnless(HAS_TORCH, "Brain v4 loaded-inference smoke tests require optional torch")
    def test_loaded_inference_suppresses_generation_warnings_in_normal_mode(self):
        runner = BrainV4Inference()
        runner.model = _WarningModel()
        runner.tokenizer = _GeneratingTokenizer()

        with patch.dict("os.environ", {}, clear=True), redirect_stdout(StringIO()) as stdout, redirect_stderr(StringIO()) as stderr:
            result = runner.diagnose(terminal_error="TypeError: bad", context="x + y")

        self.assertTrue(result["available"])
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_generation_kwargs_omit_sampling_options_when_sampling_disabled(self):
        kwargs = build_generation_kwargs(
            {"input_ids": [1]},
            max_new_tokens=128,
            do_sample=False,
            pad_token_id=0,
            temperature=0.7,
            top_p=0.9,
            top_k=40,
        )

        self.assertFalse(kwargs["do_sample"])
        self.assertNotIn("temperature", kwargs)
        self.assertNotIn("top_p", kwargs)
        self.assertNotIn("top_k", kwargs)

    @unittest.skipUnless(HAS_TORCH, "Brain v4 loaded-inference smoke tests require optional torch")
    def test_runtime_inference_uses_token_env_override_and_eos(self):
        runner = BrainV4Inference()
        runner.model = _KwargCaptureModel()
        runner.tokenizer = _GeneratingTokenizer()

        with patch.dict("os.environ", {"GHOSTFIX_BRAIN_MAX_NEW_TOKENS": "77"}, clear=True), redirect_stdout(StringIO()):
            result = runner.diagnose(terminal_error="TypeError: bad", context="x + y")

        self.assertTrue(result["available"])
        self.assertEqual(runner.model.kwargs["max_new_tokens"], 77)
        self.assertEqual(runner.model.kwargs["eos_token_id"], runner.tokenizer.eos_token_id)

    @unittest.skipUnless(HAS_TORCH, "Brain v4 loaded-inference smoke tests require optional torch")
    def test_runtime_inference_default_tokens_are_shorter(self):
        runner = BrainV4Inference()
        runner.model = _KwargCaptureModel()
        runner.tokenizer = _GeneratingTokenizer()

        with patch.dict("os.environ", {}, clear=True), redirect_stdout(StringIO()):
            result = runner.diagnose(terminal_error="TypeError: bad", context="x + y")

        self.assertTrue(result["available"])
        self.assertEqual(runner.model.kwargs["max_new_tokens"], DEFAULT_MAX_NEW_TOKENS)

    @unittest.skipUnless(HAS_TORCH, "Brain v4 loaded-inference smoke tests require optional torch")
    def test_loaded_inference_debug_exposes_raw_and_parsed_for_evaluation(self):
        runner = BrainV4Inference()
        runner.model = _FakeModel()
        runner.tokenizer = _GeneratingTokenizer()

        with redirect_stdout(StringIO()):
            result = runner.diagnose(terminal_error="TypeError: bad", context="x + y", include_debug=True)

        self.assertTrue(result["available"])
        self.assertEqual(set(result["diagnosis"]), set(BRAIN_V4_SCHEMA_KEYS))
        self.assertIn("raw_output", result)
        self.assertIn("parsed_output", result)
        self.assertIn("context", result["parsed_output"])
        self.assertNotIn("context", result["diagnosis"])

    @unittest.skipUnless(HAS_TORCH, "Brain v4 loaded-inference smoke tests require optional torch")
    def test_inference_decodes_only_generated_continuation(self):
        runner = BrainV4Inference()
        runner.model = _PromptPlusContinuationModel()
        runner.tokenizer = _ContinuationOnlyTokenizer()

        with redirect_stdout(StringIO()):
            result = runner.diagnose(terminal_error="TypeError: bad", context="x + y", include_debug=True)

        self.assertTrue(result["available"])
        self.assertEqual(runner.tokenizer.decoded_token_ids, [201, 202])
        self.assertEqual(result["raw_output"], runner.tokenizer.generated_text)

    @unittest.skipUnless(HAS_TORCH, "Brain v4 loaded-inference smoke tests require optional torch")
    def test_prompt_text_is_not_included_in_parsed_output(self):
        runner = BrainV4Inference()
        runner.model = _PromptPlusContinuationModel()
        runner.tokenizer = _ContinuationOnlyTokenizer()

        with redirect_stdout(StringIO()):
            result = runner.diagnose(terminal_error="TypeError: bad", context="x + y", include_debug=True)

        parsed = result["parsed_output"]
        self.assertEqual(parsed["root_cause"], "typeerror_bad_operands")
        self.assertNotIn("<|im_start|>system", json.dumps(parsed))
        self.assertNotIn(TRAINING_SCHEMA_SYSTEM_PROMPT, json.dumps(parsed))

    @unittest.skipUnless(HAS_TORCH, "Brain v4 loaded-inference smoke tests require optional torch")
    def test_finalizer_receives_parsed_assistant_json(self):
        runner = BrainV4Inference()
        runner.model = _PromptPlusContinuationModel()
        runner.tokenizer = _ContinuationOnlyTokenizer()
        final = finalize_brain_v4_output(_record()["output"])

        with patch("ml.brain_v4_inference.finalize_brain_v4_output", return_value=final) as finalizer:
            with redirect_stdout(StringIO()):
                result = runner.diagnose(terminal_error="TypeError: bad", context="x + y")

        self.assertTrue(result["available"])
        parsed_arg = finalizer.call_args.args[0]
        self.assertIsInstance(parsed_arg, dict)
        self.assertEqual(parsed_arg["root_cause"], "typeerror_bad_operands")
        self.assertNotIn("<|im_start|>system", json.dumps(parsed_arg))

    def test_tokenizes_two_records_with_flat_labels(self):
        records = [_record(), _record()]
        with redirect_stdout(StringIO()):
            tokenized = tokenize_records(_FakeTokenizer(), records, max_seq_length=512)

        self.assertEqual(len(tokenized["input_ids"]), 2)
        for key in ("input_ids", "attention_mask", "labels"):
            self.assertEqual(len(tokenized[key]), 2)
            for row in tokenized[key]:
                self.assertIsInstance(row, list)
                self.assertTrue(row)
                self.assertTrue(all(isinstance(item, int) for item in row))
                self.assertFalse(any(isinstance(item, list) for item in row))

    def test_sft_labels_mask_prompt_and_train_on_target_json(self):
        record = _record()
        record["output"] = json.dumps(record["output"], sort_keys=True, separators=(",", ":"))
        tokenizer = _CharTokenizer()

        row = tokenize_sft_record(tokenizer, record, max_seq_length=2048)

        first_supervised = next(index for index, value in enumerate(row["labels"]) if value != -100)
        self.assertGreater(first_supervised, 0)
        self.assertTrue(all(value == -100 for value in row["labels"][:first_supervised]))
        self.assertTrue(all(isinstance(value, int) for value in row["labels"]))
        self.assertTrue(all(not isinstance(value, list) for value in row["labels"]))
        supervised = [value for value in row["labels"] if value != -100]
        decoded = tokenizer.decode(supervised, skip_special_tokens=True)
        self.assertIn('"root_cause":"typeerror_bad_operands"', decoded)
        self.assertIn('"suggested_fix":"Convert or validate operands before adding them."', decoded)
        self.assertEqual(len(row["input_ids"]), len(row["attention_mask"]))
        self.assertEqual(len(row["input_ids"]), len(row["labels"]))

    def test_capped_training_selection_shuffles_instead_of_first_n(self):
        records = [_training_record("TypeError", f"type_root_{index}", real=True) for index in range(20)]

        selected = select_shuffled_training_records(records, 5, seed=7)

        self.assertEqual(len(selected), 5)
        self.assertNotEqual([record["input"] for record in selected], [record["input"] for record in records[:5]])

    def test_balanced_training_selection_includes_common_errors_and_mix(self):
        records = []
        for error_type in COMMON_ERROR_TYPES:
            for index in range(6):
                records.append(_training_record(error_type, f"{error_type.lower()}_real_{index}", real=True))
                records.append(_training_record(error_type, f"{error_type.lower()}_schema_{index}", real=False))
        selected = select_balanced_training_records(records, 28, seed=11)
        selected_outputs = [json.loads(record["output"]) for record in selected]
        selected_errors = {output["error_type"] for output in selected_outputs}
        selected_instructions = {record["instruction"] for record in selected}

        self.assertEqual(len(selected), 28)
        self.assertTrue(set(COMMON_ERROR_TYPES).issubset(selected_errors))
        self.assertIn("Return ONLY valid JSON with exact schema", selected_instructions)
        self.assertIn("Analyze the terminal error and return strict JSON.", selected_instructions)

    def test_dataset_selection_debug_prints_distribution(self):
        records = [
            _training_record("TypeError", "wrong_type_or_callable_mismatch", real=True),
            _training_record("NameError", "undefined_variable_or_missing_import", real=False),
        ]
        buffer = StringIO()

        with redirect_stdout(buffer):
            print_dataset_selection_debug(records, split_name="train")

        text = buffer.getvalue()
        self.assertIn("Selected train count: 2", text)
        self.assertIn("TypeError", text)
        self.assertIn("undefined_variable_or_missing_import", text)

    def test_overfit_smoke_selection_prefers_high_quality_common_errors(self):
        records = [_training_record("CustomError", "unknown", real=True, confidence=50)]
        for error_type in COMMON_ERROR_TYPES:
            records.append(_training_record(error_type, f"{error_type.lower()}_quality", real=True, confidence=88))

        selected = select_overfit_smoke_records(records, 7, seed=3)
        outputs = [json.loads(record["output"]) for record in selected]

        self.assertEqual(len(selected), 7)
        self.assertTrue(all(output["error_type"] in COMMON_ERROR_TYPES for output in outputs))
        self.assertTrue(all(output["confidence"] >= 80 for output in outputs))
        self.assertTrue(all(output["root_cause"] != "unknown" for output in outputs))

    def test_training_text_uses_chat_style_and_ends_with_json(self):
        record = _record()
        record["output"] = json.dumps(record["output"], sort_keys=True, separators=(",", ":"))
        text = format_training_text(record)

        self.assertIn("You MUST return ONLY valid JSON.", text)
        self.assertIn("You MUST use EXACT keys:", text)
        self.assertIn("Do NOT use any other keys.", text)
        self.assertIn("<|im_start|>user\nterminal_error:", text)
        self.assertIn("<|im_start|>assistant\n{", text)
        self.assertTrue(text.endswith(record["output"]))

    def test_inference_prompt_ignores_tokenizer_chat_template_to_match_training(self):
        prompt = render_brain_v4_chat_prompt(_ChatTemplateTokenizer(), "terminal_error:\nTypeError: bad")

        self.assertEqual(
            prompt,
            (
                f"<|im_start|>system\n{TRAINING_SCHEMA_SYSTEM_PROMPT}<|im_end|>\n"
                f"<|im_start|>user\nterminal_error:\nTypeError: bad<|im_end|>\n"
                f"<|im_start|>assistant\n"
            ),
        )

    def test_inference_prompt_fallback_matches_training_chat_style(self):
        prompt = render_brain_v4_chat_prompt(_FakeTokenizer(), "terminal_error:\nTypeError: bad")

        self.assertIn(f"<|im_start|>system\n{TRAINING_SCHEMA_SYSTEM_PROMPT}<|im_end|>", prompt)
        self.assertIn("<|im_start|>user\nterminal_error:\nTypeError: bad<|im_end|>", prompt)
        self.assertTrue(prompt.endswith("<|im_start|>assistant\n"))

    @unittest.skipUnless(HAS_TORCH, "Brain v4 collator tensor test requires optional torch")
    def test_collator_pads_labels_with_ignore_index(self):
        features = {
            "input_ids": [[1, 2, 3], [4, 5]],
            "attention_mask": [[1, 1, 1], [1, 1]],
            "labels": [[1, 2, 3], [4, 5]],
        }
        rows = [{key: features[key][index] for key in features} for index in range(2)]
        batch = CausalLMPaddingCollator(_FakeTokenizer())(rows)

        self.assertEqual(batch["input_ids"].shape[1], 3)
        self.assertEqual(batch["labels"][1, 2].item(), -100)


def _record() -> dict:
    return {
        "instruction": "Analyze the terminal error and return strict JSON.",
        "input": "terminal_error:\nTraceback\nTypeError: bad\ncode_context:\nx + y",
        "output": {
            "language": "python",
            "framework": "python",
            "error_type": "TypeError",
            "root_cause": "typeerror_bad_operands",
            "likely_root_cause": "The operands are incompatible.",
            "evidence": ["Traceback contains TypeError."],
            "suggested_fix": "Convert or validate operands before adding them.",
            "confidence": 88,
            "safe_to_autofix": False,
        },
    }


def _training_record(error_type: str, root_cause: str, *, real: bool, confidence: int = 85) -> dict:
    return {
        "instruction": (
            "Analyze the terminal error and return strict JSON."
            if real
            else "Return ONLY valid JSON with exact schema"
        ),
        "input": f"Traceback\n{error_type}: sample {root_cause}",
        "output": json.dumps(
            {
                "language": "python",
                "framework": "python",
                "error_type": error_type,
                "root_cause": root_cause,
                "likely_root_cause": f"{root_cause} caused the sample error.",
                "evidence": [f"{error_type}: sample {root_cause}"],
                "suggested_fix": f"Apply the targeted fix for {root_cause}.",
                "confidence": confidence,
                "safe_to_autofix": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


class _FakeTokenizer:
    eos_token = "<eos>"
    eos_token_id = 0
    pad_token_id = 0

    def __call__(
        self,
        texts,
        *,
        truncation=True,
        max_length=16,
        padding=False,
        add_special_tokens=True,
    ):
        input_ids = []
        attention_mask = []
        for text in texts:
            ids = [(ord(char) % 89) + 1 for char in text][:max_length]
            input_ids.append(ids)
            attention_mask.append([1] * len(ids))
        return {"input_ids": input_ids, "attention_mask": attention_mask}


class _CharTokenizer:
    eos_token = "<eos>"
    eos_token_id = 3
    pad_token_id = 0

    def __call__(
        self,
        texts,
        *,
        truncation=False,
        max_length=None,
        padding=False,
        add_special_tokens=True,
    ):
        input_ids = []
        attention_mask = []
        for text in texts:
            ids = [ord(char) for char in text]
            if max_length:
                ids = ids[:max_length]
            input_ids.append(ids)
            attention_mask.append([1] * len(ids))
        return {"input_ids": input_ids, "attention_mask": attention_mask}

    def decode(self, token_ids, skip_special_tokens=False):
        return "".join(chr(item) for item in token_ids if item != self.eos_token_id or not skip_special_tokens)


class _ChatTemplateTokenizer:
    def apply_chat_template(self, messages, *, tokenize=False, add_generation_prompt=True):
        self.messages = messages
        self.tokenize = tokenize
        self.add_generation_prompt = add_generation_prompt
        return "CHAT:" + "|".join(f"{message['role']}:{message['content']}" for message in messages) + "|GEN"


class _FakeModel:
    def generate(self, **kwargs):
        import torch

        return torch.tensor([[1, 2, 3]])


class _WarningModel:
    def generate(self, **kwargs):
        import torch
        import warnings

        warnings.warn("transformers generation warning: temperature is ignored when do_sample=False")
        return torch.tensor([[1, 2, 3]])


class _KwargCaptureModel:
    def generate(self, **kwargs):
        import torch

        self.kwargs = kwargs
        return torch.tensor([[1, 2, 3]])


class _PromptPlusContinuationModel:
    def generate(self, **kwargs):
        import torch

        return torch.tensor([[101, 102, 103, 104, 201, 202]])


class _ContinuationOnlyTokenizer:
    eos_token_id = 0

    def __init__(self):
        self.generated_text = json.dumps(_record()["output"])
        self.decoded_token_ids = []

    def __call__(self, text, return_tensors="pt"):
        import torch

        self.prompt = text
        return {"input_ids": torch.tensor([[101, 102, 103, 104]])}

    def decode(self, token_ids, skip_special_tokens=True):
        self.decoded_token_ids = [int(item) for item in token_ids]
        if self.decoded_token_ids != [201, 202]:
            return self.prompt + self.generated_text
        return self.generated_text


class _GeneratingTokenizer:
    eos_token_id = 0

    def __call__(self, text, return_tensors="pt"):
        import torch

        return {"input_ids": torch.tensor([[1, 2]])}

    def decode(self, token_ids, skip_special_tokens=True):
        return json.dumps({
            **_record()["output"],
            "context": "x + y",
            "metadata": {"source": "model"},
            "error_log": "TypeError: bad",
            "failing_line": "x + y",
        })


if __name__ == "__main__":
    unittest.main()
