from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ml.prepare_brain_v4_lora_dataset import BRAIN_V4_SCHEMA_KEYS, build_dataset


class BrainV4DatasetBuilderTests(unittest.TestCase):
    def test_builder_filters_vague_and_keeps_strict_record(self):
        good = {
            "error": "Traceback (most recent call last):\n  File \"app.py\", line 2\nTypeError: bad",
            "error_type": "TypeError",
            "context": "result = count + name",
            "failing_line": "result = count + name",
            "cause": "The code adds incompatible value types.",
            "fix": "Convert count to a string before concatenation or use numeric values consistently.",
            "quality_score": 8.5,
            "auto_fix_allowed": False,
            "auto_fix_allowed_safe": False,
            "complexity_class": "needs_context_reasoning",
        }
        vague = {
            **good,
            "fix": "Fix it.",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "records.jsonl"
            source.write_text(
                json.dumps(good) + "\n" + json.dumps(vague) + "\n",
                encoding="utf-8",
            )
            result = build_dataset(sources=[source], val_ratio=0.5)

        rows = result["train"] + result["val"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["instruction"], "Analyze the terminal error and return strict JSON.")
        row_text = json.dumps(rows[0], ensure_ascii=False)
        self.assertNotIn("error_type_hint", row_text)
        self.assertNotIn("code_context", row_text)
        self.assertNotIn("project_hints", row_text)
        self.assertNotIn("terminal_error", row_text)
        self.assertIsInstance(rows[0]["output"], str)
        output = json.loads(rows[0]["output"])
        self.assertEqual(set(output), set(BRAIN_V4_SCHEMA_KEYS))
        self.assertNotIn("error_type_hint", output)
        self.assertNotIn("code_context", output)
        self.assertNotIn("project_hints", output)
        self.assertNotIn("terminal_error", output)
        self.assertEqual(output["error_type"], "TypeError")
        self.assertEqual(output["root_cause"], "wrong_type_or_callable_mismatch")
        self.assertNotEqual(output["likely_root_cause"].lower(), "unknown")
        self.assertTrue(output["suggested_fix"])
        self.assertGreaterEqual(output["confidence"], 50)
        self.assertLessEqual(output["confidence"], 65)
        self.assertFalse(output["safe_to_autofix"])
        self.assertEqual(result["rejected"]["vague_fix"], 1)

    def test_default_builder_adds_json_only_seed_examples(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "empty.jsonl"
            source.write_text("", encoding="utf-8")
            result = build_dataset(sources=[source], include_json_only_examples=True)

        rows = result["train"] + result["val"]
        self.assertGreaterEqual(len(rows), 50)
        self.assertGreaterEqual(len(rows), 720 * 3)
        for row in rows:
            self.assertEqual(row["instruction"], "Return ONLY valid JSON with exact schema")
            row_text = json.dumps(row, ensure_ascii=False)
            self.assertNotIn("error_type_hint", row_text)
            self.assertNotIn("code_context", row_text)
            self.assertNotIn("project_hints", row_text)
            self.assertNotIn("terminal_error", row_text)
            self.assertIsInstance(row["output"], str)
            parsed = json.loads(row["output"])
            self.assertIsInstance(parsed, dict)
            self.assertEqual(set(parsed), set(BRAIN_V4_SCHEMA_KEYS))
            self.assertNotIn(parsed["root_cause"].lower(), {"unknown", ""})
            self.assertNotIn(parsed["likely_root_cause"].lower(), {"unknown", ""})
            self.assertTrue(parsed["suggested_fix"])

    def test_builder_rejects_generic_unknown_target_output(self):
        record = {
            "error": "Traceback (most recent call last):\n  File \"app.py\", line 2\nCustomError: bad",
            "error_type": "CustomError",
            "context": "run_custom()",
            "failing_line": "run_custom()",
            "cause": "unknown",
            "fix": "Add validation for the custom input before calling run_custom.",
            "auto_fix_allowed": False,
            "auto_fix_allowed_safe": False,
            "complexity_class": "needs_context_reasoning",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "records.jsonl"
            source.write_text(json.dumps(record) + "\n", encoding="utf-8")
            result = build_dataset(sources=[source])

        self.assertEqual(len(result["train"] + result["val"]), 0)
        self.assertEqual(result["rejected"]["generic_target_output"], 1)

    def test_builder_rejects_unclear_autofix_label(self):
        record = {
            "error": "Traceback (most recent call last):\n  File \"app.py\", line 2\nNameError: name 'x' is not defined",
            "error_type": "NameError",
            "context": "print(x)",
            "failing_line": "print(x)",
            "cause": "The variable is used before it is defined.",
            "fix": "Define x before printing it or correct the variable name.",
            "auto_fix_allowed": True,
            "auto_fix_allowed_safe": False,
            "complexity_class": "needs_context_reasoning",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "records.jsonl"
            source.write_text(json.dumps(record) + "\n", encoding="utf-8")
            result = build_dataset(sources=[source])

        self.assertEqual(len(result["train"] + result["val"]), 0)
        self.assertEqual(result["rejected"]["unsafe_autofix_not_clearly_labeled"], 1)


if __name__ == "__main__":
    unittest.main()
