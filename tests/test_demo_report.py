from __future__ import annotations

import unittest

from core.demo_report import REPORT_JSON, REPORT_MD, _write_reports


class DemoReportTests(unittest.TestCase):
    def test_demo_report_writes_json_and_markdown(self):
        rows = [
            {
                "scenario_name": "Sample",
                "command": "python sample.py",
                "detected_error_type": "RuntimeError",
                "detected_framework": "python",
                "root_cause": "sample_root_cause",
                "likely_root_cause": "A readable explanation.",
                "suggested_fix": "Fix the sample.",
                "confidence": 90,
                "source": "parser",
                "auto_fix_available": False,
                "safety_reason": "Manual review required.",
                "pass": True,
            }
        ]

        _write_reports(rows)

        self.assertTrue(REPORT_JSON.exists())
        self.assertTrue(REPORT_MD.exists())
        self.assertIn("sample_root_cause", REPORT_JSON.read_text(encoding="utf-8"))
        self.assertIn("GhostFix Demo Readiness Report", REPORT_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
