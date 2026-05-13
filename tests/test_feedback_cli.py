from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from core.feedback import feedback_path, load_feedback
from core.incidents import make_incident, record_incident


class FeedbackCliTests(unittest.TestCase):
    def test_good_feedback_is_saved_locally(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            record_incident(
                make_incident(
                    command="python app.py",
                    file="app.py",
                    language="python",
                    runtime="python",
                    error_type="SyntaxError",
                    cause="missing colon",
                    fix="add colon",
                    confidence=99,
                    auto_fix_available=True,
                    resolved_after_fix=False,
                ),
                root=root,
            )

            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                result = runner.invoke(app, ["feedback", "--good"], catch_exceptions=False)
                rows = load_feedback(root)
                saved_path_exists = feedback_path(root).exists()
            finally:
                os.chdir(old_cwd)

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Feedback saved locally.", result.output)
        self.assertTrue(saved_path_exists)
        self.assertEqual(rows[0]["rating"], "good")
        self.assertEqual(rows[0]["note"], "")
        self.assertEqual(rows[0]["incident"]["error_type"], "SyntaxError")
        self.assertEqual(rows[0]["latest_incident_id"], rows[0]["incident"]["id"])

    def test_bad_feedback_with_note_is_saved_locally(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            record_incident(
                make_incident(
                    command="python server.py",
                    file="server.py",
                    language="python",
                    runtime="fastapi",
                    error_type="ModuleNotFoundError",
                    cause="missing dependency",
                    fix="install dependency",
                    confidence=92,
                    auto_fix_available=False,
                    resolved_after_fix=False,
                ),
                root=root,
            )

            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                result = runner.invoke(
                    app,
                    ["feedback", "--bad", "--note", "wrong root cause"],
                    catch_exceptions=False,
                )
                rows = load_feedback(root)
            finally:
                os.chdir(old_cwd)

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Feedback saved locally.", result.output)
        self.assertEqual(rows[0]["rating"], "bad")
        self.assertEqual(rows[0]["note"], "wrong root cause")
        self.assertEqual(rows[0]["incident"]["runtime"], "fastapi")

    def test_feedback_works_with_no_incidents(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                result = runner.invoke(app, ["feedback", "--good"], catch_exceptions=False)
                rows = load_feedback(root)
            finally:
                os.chdir(old_cwd)

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Feedback saved locally.", result.output)
        self.assertEqual(rows[0]["rating"], "good")
        self.assertIsNone(rows[0]["latest_incident_id"])
        self.assertIsNone(rows[0]["incident"])


if __name__ == "__main__":
    unittest.main()
