from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from typer.testing import CliRunner

from agent.daemon_runtime import daemon_state_path, daemon_stop_path, read_daemon_status
from cli.main import app
from core.incidents import load_incidents


class DaemonRuntimeTests(unittest.TestCase):
    def test_daemon_start_reuses_watch_mode_and_records_incident(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "fail.py"
            script.write_text("missing_value\n", encoding="utf-8")
            command = f'"{sys.executable}" "{script}"'

            with _working_directory(root):
                result = runner.invoke(
                    app,
                    ["daemon", "start", command, "--max-runs", "1", "--restart-delay", "0"],
                    catch_exceptions=False,
                )
                rows = load_incidents(root)
                status = read_daemon_status(root)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("GhostFix daemon starting", result.output)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["error_type"], "NameError")
        self.assertEqual(status["status"], "stopped")
        self.assertEqual(status["runs"], 1)

    def test_daemon_status_reads_local_state(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            daemon_state_path(root).parent.mkdir(parents=True)
            daemon_state_path(root).write_text(
                '{"status":"running","pid":123,"command":"python app.py","runs":2}',
                encoding="utf-8",
            )

            with _working_directory(root):
                result = runner.invoke(app, ["daemon", "status"], catch_exceptions=False)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("running", result.output)
        self.assertIn("python app.py", result.output)

    def test_daemon_stop_writes_stop_request(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with _working_directory(root):
                result = runner.invoke(app, ["daemon", "stop"], catch_exceptions=False)
                stop_exists = daemon_stop_path(root).exists()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(stop_exists)
        self.assertIn("Stop requested", result.output)


@contextmanager
def _working_directory(path: Path):
    old_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
