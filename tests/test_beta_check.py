from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.main import app


class BetaCheckTests(unittest.TestCase):
    def test_beta_check_passes_in_normal_local_environment(self):
        result = CliRunner().invoke(app, ["beta-check"], catch_exceptions=False)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("PASS: doctor", result.output)
        self.assertIn("PASS: quickstart", result.output)
        self.assertIn("PASS: examples", result.output)
        self.assertIn("PASS: dry-run", result.output)
        self.assertIn("PASS: audit command", result.output)
        self.assertIn("PASS: rollback command", result.output)
        self.assertIn("PASS: feedback command", result.output)
        self.assertIn("PASS: local reports path", result.output)
        self.assertIn("GhostFix is ready for closed beta trial.", result.output)

    def test_beta_check_reports_blocker_safely(self):
        fake_checks = [
            {"name": "doctor", "ok": True, "detail": "required local checks passed"},
            {"name": "dry-run", "ok": False, "detail": "file changed"},
        ]

        with patch("cli.main._beta_checks", return_value=fake_checks):
            result = CliRunner().invoke(app, ["beta-check"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("BLOCKER: dry-run - file changed", result.output)
        self.assertIn("GhostFix is not ready for closed beta trial.", result.output)
        self.assertIn("- dry-run: file changed", result.output)

    def test_closed_beta_docs_and_checklist_exist(self):
        guide = Path("docs/CLOSED_BETA_GUIDE.md").read_text(encoding="utf-8")
        readme = Path("README.md").read_text(encoding="utf-8")
        checklist = Path("RELEASE_CANDIDATE_CHECKLIST.md").read_text(encoding="utf-8")

        self.assertIn("# GhostFix Closed Beta Guide", guide)
        self.assertIn("Who Should Try GhostFix", guide)
        self.assertIn("ghostfix beta-check", guide)
        self.assertIn("What GhostFix Never Uploads Automatically", guide)
        self.assertIn("## Closed Beta Trial", readme)
        self.assertIn("## Closed Beta Checklist", checklist)
        self.assertIn("beta-check pass", checklist)
        self.assertIn("dry-run tested", checklist)
        self.assertIn("rollback tested", checklist)
        self.assertIn("audit tested", checklist)
        self.assertIn("feedback tested", checklist)


if __name__ == "__main__":
    unittest.main()
