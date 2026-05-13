from __future__ import annotations

import unittest

from ml.evaluate_watch_mode import evaluate_watch_mode, write_reports, JSON_REPORT, MD_REPORT


class WatchModeBenchmarkTests(unittest.TestCase):
    def test_watch_mode_cases_score_expected_axes(self):
        report = evaluate_watch_mode()

        self.assertEqual(report["record_count"], 7)
        self.assertEqual(report["language_accuracy"], 1.0)
        self.assertEqual(report["runtime_accuracy"], 1.0)
        self.assertEqual(report["error_type_accuracy"], 1.0)
        self.assertEqual(report["root_cause_keyword_match_rate"], 1.0)
        self.assertEqual(report["auto_fix_safety_match_rate"], 1.0)
        self.assertEqual(report["pass_count"], 7)

    def test_watch_mode_reports_are_written(self):
        report = evaluate_watch_mode()

        write_reports(report)

        self.assertTrue(JSON_REPORT.exists())
        self.assertTrue(MD_REPORT.exists())
        self.assertIn("watch_mode_cases", JSON_REPORT.read_text(encoding="utf-8"))
        self.assertIn("Watch Mode Accuracy Report", MD_REPORT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
