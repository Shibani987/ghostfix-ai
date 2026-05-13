from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from core.fix_audit import fix_audit_path, load_fix_audits
from core.incidents import load_incidents


class TrustSafetyTests(unittest.TestCase):
    def test_run_dry_run_diagnoses_without_modifying_file(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "bad.py"
            original = "if True\n    print('yes')\n"
            path.write_text(original, encoding="utf-8")

            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                result = runner.invoke(app, ["run", str(path), "--fix", "--dry-run"], catch_exceptions=False)
                after = path.read_text(encoding="utf-8")
                audits = load_fix_audits(root)
            finally:
                os.chdir(old_cwd)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("DRY_RUN: enabled", result.output)
        self.assertIn("No code will be modified", result.output)
        self.assertIn("No code was modified.", result.output)
        self.assertEqual(after, original)
        self.assertEqual(len(audits), 1)
        self.assertFalse(audits[0]["user_confirmed"])
        self.assertFalse(audits[0]["rollback_available"])
        self.assertIn("dry-run", audits[0]["validator_result"])

    def test_auto_fix_audit_logging_and_rollback_linkage(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "bad.py"
            path.write_text("if True\n    print('yes')\n", encoding="utf-8")

            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                result = runner.invoke(app, ["run", str(path), "--fix", "--auto-approve"], catch_exceptions=False)
                audits = load_fix_audits(root)
                incidents = load_incidents(root)
                patched = path.read_text(encoding="utf-8")
                backup_exists = Path(audits[0]["backup_path"]).exists() if audits else False
            finally:
                os.chdir(old_cwd)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Rollback is available.", result.output)
        self.assertIn("if True:", patched)
        self.assertEqual(len(audits), 1)
        self.assertTrue(audits[0]["user_confirmed"])
        self.assertTrue(audits[0]["rollback_available"])
        self.assertTrue(backup_exists)
        self.assertTrue(incidents[-1]["rollback_metadata"]["backup"])
        self.assertEqual(audits[0]["backup_path"], incidents[-1]["rollback_metadata"]["backup"])

    def test_audit_command_and_last_limit(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "one.py"
            second = root / "two.py"
            first.write_text("if True\n    print('one')\n", encoding="utf-8")
            second.write_text("if True\n    print('two')\n", encoding="utf-8")

            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                runner.invoke(app, ["run", str(first), "--fix", "--dry-run"], catch_exceptions=False)
                runner.invoke(app, ["run", str(second), "--fix", "--dry-run"], catch_exceptions=False)
                result = runner.invoke(app, ["audit", "--last", "1"], catch_exceptions=False)
                audit_exists = fix_audit_path(root).exists()
            finally:
                os.chdir(old_cwd)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(audit_exists)
        self.assertIn("GhostFix Fix Audit", result.output)
        self.assertIn("AUDIT_TARGET:", result.output)
        self.assertIn("two.py", result.output)
        self.assertNotIn("one.py", result.output)
        self.assertIn("USER_CONFIRMED: no", result.output)
        self.assertIn("ROLLBACK_AVAILABLE: no", result.output)

    def test_watch_dry_run_prints_safety_words(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "bad.py"
            script.write_text("if True\n    print('yes')\n", encoding="utf-8")

            result = runner.invoke(
                app,
                ["watch", f"python {script}", "--fix", "--dry-run", "--cwd", str(root)],
                catch_exceptions=False,
            )
            after = script.read_text(encoding="utf-8")

        self.assertNotEqual(result.exit_code, 2, result.output)
        self.assertIn("DRY_RUN: enabled", result.output)
        self.assertIn("No code will be modified", result.output)
        self.assertEqual(after, "if True\n    print('yes')\n")

    def test_trust_and_safety_docs_and_readme_section_exist(self):
        trust = Path("docs/TRUST_AND_SAFETY.md").read_text(encoding="utf-8")
        readme = Path("README.md").read_text(encoding="utf-8")

        self.assertIn("# GhostFix Trust And Safety", trust)
        self.assertIn("Dry-run", trust)
        self.assertIn(".ghostfix/fix_audit.jsonl", trust)
        self.assertIn("ghostfix audit --last 10", trust)
        self.assertIn("## Trust & Safety", readme)
        self.assertIn("ghostfix run tests/manual_errors/name_error.py --dry-run", readme)
        self.assertIn("ghostfix audit --last 10", readme)


if __name__ == "__main__":
    unittest.main()
