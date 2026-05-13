from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from typer.testing import CliRunner

from agent.terminal_watcher import TerminalWatcher
from cli.main import app
from core.incidents import incidents_path, load_incidents, make_incident, record_incident


def normalize_cli_output(text: str) -> str:
    """Strip ANSI escape sequences and normalize Rich line wrapping."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    text = ansi_escape.sub('', text)
    return " ".join(text.split())


class IncidentMemoryTests(unittest.TestCase):
    def test_record_incident_writes_required_jsonl_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            incident = make_incident(
                command="python app.py",
                file="app.py",
                language="python",
                runtime="python",
                error_type="NameError",
                cause="A variable is referenced before assignment.",
                fix="Define the variable before using it.",
                confidence=0.87,
                auto_fix_available=True,
                resolved_after_fix=False,
            )

            written = record_incident(incident, root=root)

            self.assertTrue(written)
            path = incidents_path(root)
            self.assertTrue(path.exists())
            row = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual(
                set(row),
                {
                    "timestamp",
                    "command",
                    "file",
                    "language",
                    "runtime",
                    "error_type",
                    "cause",
                    "fix",
                    "confidence",
                    "auto_fix_available",
                    "resolved_after_fix",
                    "rollback_metadata",
                },
            )
            self.assertEqual(row["confidence"], 87)
            self.assertEqual(row["rollback_metadata"], {})

    def test_duplicate_repeated_incidents_are_suppressed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            incident = make_incident(
                command="python app.py",
                file="app.py",
                language="python",
                runtime="python",
                error_type="NameError",
                cause="missing variable",
                fix="define it",
                confidence=80,
                auto_fix_available=False,
                resolved_after_fix=False,
            )

            self.assertTrue(record_incident(incident, root=root))
            self.assertFalse(record_incident(incident, root=root))

            self.assertEqual(len(load_incidents(root)), 1)

    def test_cli_incidents_supports_last_limit(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(3):
                record_incident(
                    make_incident(
                        command=f"python case_{index}.py",
                        file=f"case_{index}.py",
                        language="python",
                        runtime="python",
                        error_type=f"Error{index}",
                        cause=f"cause {index}",
                        fix=f"fix {index}",
                        confidence=70 + index,
                        auto_fix_available=False,
                        resolved_after_fix=False,
                    ),
                    root=root,
                )

            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                result = runner.invoke(app, ["incidents", "--last", "2"], catch_exceptions=False)
            finally:
                os.chdir(old_cwd)

        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("Error0", result.output)
        self.assertIn("Error1", result.output)
        self.assertIn("Error2", result.output)

    def test_watch_mode_records_local_incident_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "fail.py"
            script.write_text("missing_value\n", encoding="utf-8")
            command = f'"{sys.executable}" "{script}"'
            watcher = TerminalWatcher(command, cwd=str(root), auto_fix=False, verbose=False)

            with redirect_stdout(StringIO()):
                result = watcher.watch()

            rows = load_incidents(root)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["error_type"], "NameError")
        self.assertEqual(rows[0]["command"], command)
        self.assertFalse(rows[0]["resolved_after_fix"])

    def test_cli_rollback_last_restores_backup_when_available(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "app.py"
            backup = root / "app.py.bak_20260512_120000"
            target.write_text("patched\n", encoding="utf-8")
            backup.write_text("original\n", encoding="utf-8")
            record_incident(
                make_incident(
                    command="python app.py",
                    file=str(target),
                    language="python",
                    runtime="python",
                    error_type="SyntaxError",
                    cause="missing colon",
                    fix="add colon",
                    confidence=99,
                    auto_fix_available=True,
                    resolved_after_fix=False,
                    rollback_metadata={
                        "backup": str(backup),
                        "target": str(target),
                        "sandbox_validated": True,
                    },
                ),
                root=root,
            )

            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                result = runner.invoke(app, ["rollback", "last"], input="y\n", catch_exceptions=False)
                restored_text = target.read_text(encoding="utf-8")
                backup_exists = backup.exists()
            finally:
                os.chdir(old_cwd)

            self.assertEqual(result.exit_code, 0)
            self.assertIn("Rollback completed.", result.output)
            self.assertEqual(restored_text, "original\n")
            self.assertTrue(backup_exists)

    def test_cli_rollback_last_reports_no_rollback_when_metadata_missing(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            record_incident(
                make_incident(
                    command="python app.py",
                    file="app.py",
                    language="python",
                    runtime="python",
                    error_type="NameError",
                    cause="missing variable",
                    fix="define it",
                    confidence=80,
                    auto_fix_available=False,
                    resolved_after_fix=False,
                ),
                root=root,
            )

            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                result = runner.invoke(app, ["rollback", "last"], catch_exceptions=False)
            finally:
                os.chdir(old_cwd)

        self.assertEqual(result.exit_code, 0)
        normalized_output = normalize_cli_output(result.output)

        self.assertIn(
            "No rollback available for the latest incident.",
            normalized_output,
        )

    def test_cli_rollback_last_fails_safely_when_backup_missing(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "app.py"
            backup = root / "missing.bak"
            target.write_text("patched\n", encoding="utf-8")
            record_incident(
                make_incident(
                    command="python app.py",
                    file=str(target),
                    language="python",
                    runtime="python",
                    error_type="SyntaxError",
                    cause="missing colon",
                    fix="add colon",
                    confidence=99,
                    auto_fix_available=True,
                    resolved_after_fix=False,
                    rollback_metadata={
                        "backup": str(backup),
                        "target": str(target),
                        "sandbox_validated": True,
                    },
                ),
                root=root,
            )

            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                result = runner.invoke(app, ["rollback", "last"], catch_exceptions=False)
                target_text = target.read_text(encoding="utf-8")
            finally:
                os.chdir(old_cwd)

            self.assertNotEqual(result.exit_code, 0)
            normalized_output = normalize_cli_output(result.output)

            self.assertIn(
                "Rollback failed: backup file",
                normalized_output,
            )
            self.assertIn(
                "is missing",
                normalized_output,
            )
            self.assertEqual(target_text, "patched\n")


if __name__ == "__main__":
    unittest.main()
