from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent.daemon_runtime import start_daemon
from agent.terminal_watcher import (
    MAX_HANDLED_TRACEBACK_KEYS,
    MAX_REPEATED_DUPLICATE_TRACEBACKS,
    MAX_TRACEBACK_CAPTURE_SIZE,
    TerminalWatcher,
    TracebackBlockDetector,
)
from core.incidents import load_incidents, make_incident, record_incident
from core.log_events import LogEventKind, LogEventPipeline
from core.parser import extract_runtime_error, parse_error


class WatchReliabilityTests(unittest.TestCase):
    def test_repeated_identical_crashing_logs_do_not_spam_diagnoses(self):
        traceback = (
            "Traceback (most recent call last):\n"
            "  File \"app.py\", line 1, in <module>\n"
            "    missing\n"
            "NameError: name 'missing' is not defined\n"
        )
        watcher = TerminalWatcher("python app.py")

        with patch.object(watcher, "_handle_traceback") as handle:
            watcher._drain_detected([traceback for _ in range(MAX_REPEATED_DUPLICATE_TRACEBACKS + 5)])

        self.assertEqual(handle.call_count, 1)
        key = watcher._traceback_key(traceback)
        self.assertEqual(watcher._duplicate_traceback_counts[key], MAX_REPEATED_DUPLICATE_TRACEBACKS)

    def test_handled_traceback_key_cache_is_bounded(self):
        watcher = TerminalWatcher("python app.py")

        with patch.object(watcher, "_handle_traceback"):
            for index in range(MAX_HANDLED_TRACEBACK_KEYS + 20):
                watcher._drain_detected([
                    "Traceback (most recent call last):\n"
                    f"  File \"case_{index}.py\", line 1, in <module>\n"
                    "    raise RuntimeError('boom')\n"
                    f"RuntimeError: boom {index}\n"
                ])

        self.assertLessEqual(len(watcher._handled_tracebacks), MAX_HANDLED_TRACEBACK_KEYS)
        self.assertLessEqual(len(watcher._duplicate_traceback_counts), MAX_HANDLED_TRACEBACK_KEYS)

    def test_extremely_long_traceback_capture_is_bounded(self):
        captured = []
        detector = TracebackBlockDetector(captured.append)
        detector.feed("Traceback (most recent call last):\n")
        for index in range(5000):
            detector.feed(f"  File \"app.py\", line {index}, in handler\n")
            detector.feed("    call_next()\n")
        detector.feed("RuntimeError: final failure\n")

        self.assertEqual(len(captured), 1)
        self.assertLessEqual(len(captured[0]), MAX_TRACEBACK_CAPTURE_SIZE + 200)
        self.assertIn("RuntimeError: final failure", captured[0])

    def test_partial_streaming_lines_are_merged_and_bounded(self):
        pipeline = LogEventPipeline(max_partial_size=128, max_traceback_size=512)

        pipeline.feed("x" * 1000)
        self.assertLessEqual(len(pipeline._partial_line), 128)

        events = []
        events.extend(pipeline.feed("Traceback (most recent"))
        events.extend(pipeline.feed(" call last):\n  File \"app.py\", line 2, in <module>\n"))
        events.extend(pipeline.feed("    boom\nValue"))
        events.extend(pipeline.feed("Error: split unicode cafe\n"))

        blocks = [event for event in events if event.kind == LogEventKind.PYTHON_TRACEBACK]
        self.assertEqual(len(blocks), 1)
        self.assertIn("ValueError: split unicode cafe", blocks[0].text)

    def test_unicode_logs_render_safely_with_windows_encoding(self):
        watcher = TerminalWatcher("python app.py")

        class FakeStdout:
            encoding = "cp1252"

            def __init__(self):
                self.text = ""

            def write(self, value):
                self.text += value

            def flush(self):
                pass

        fake_stdout = FakeStdout()
        with patch.object(sys, "stdout", fake_stdout):
            watcher._safe_write("starting café 🚀 नमस्ते\n")

        self.assertIn("starting café", fake_stdout.text)
        self.assertIn("?", fake_stdout.text)

    def test_malformed_traceback_parsing_returns_safe_fallback(self):
        malformed = "Traceback (most recent call last):\n\x00\x00\x00\nFile ???\n"

        parsed = parse_error(malformed)
        extracted = extract_runtime_error(object(), command="python app.py")

        self.assertIn(parsed["type"], {"UnknownError"})
        self.assertIsNone(extracted)

    def test_nested_tracebacks_keep_final_exception(self):
        output = (
            "INFO booting\n"
            "Traceback (most recent call last):\n"
            "  File \"app.py\", line 3, in load\n"
            "    int('x')\n"
            "ValueError: invalid literal for int() with base 10: 'x'\n"
            "\n"
            "During handling of the above exception, another exception occurred:\n"
            "\n"
            "Traceback (most recent call last):\n"
            "  File \"app.py\", line 8, in <module>\n"
            "    load()\n"
            "RuntimeError: startup failed\n"
            "INFO stopped\n"
        )

        extracted = extract_runtime_error(output, command="python app.py")

        self.assertEqual(extracted["type"], "RuntimeError")
        self.assertIn("startup failed", extracted["message"])

    def test_mixed_language_and_noisy_logs_do_not_crash_parser(self):
        output = (
            "webpack compiled with warnings\n"
            "GET /health 200\n"
            "Traceback (most recent call last):\n"
            "  File \"api.py\", line 4, in <module>\n"
            "    import missing_api\n"
            "ModuleNotFoundError: No module named 'missing_api'\n"
            "ReferenceError: browserValue is not defined\n"
            "npm ERR! lifecycle failed\n"
        )

        extracted = extract_runtime_error(output, command="python api.py")

        self.assertEqual(extracted["language"], "python")
        self.assertEqual(extracted["type"], "ModuleNotFoundError")

    def test_very_large_logs_keep_runtime_parser_bounded(self):
        output = ("noise line\n" * 50_000) + (
            "Traceback (most recent call last):\n"
            "  File \"app.py\", line 1, in <module>\n"
            "    raise RuntimeError('late failure')\n"
            "RuntimeError: late failure\n"
        )

        extracted = extract_runtime_error(output, command="python app.py")

        self.assertEqual(extracted["type"], "RuntimeError")

    def test_repeated_duplicate_incidents_are_suppressed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            incident = make_incident(
                command="python app.py",
                file="app.py",
                language="python",
                runtime="python",
                error_type="RuntimeError",
                cause="startup failed",
                fix="inspect startup",
                confidence=80,
                auto_fix_available=False,
                resolved_after_fix=False,
            )

            results = [record_incident(incident, root=root) for _ in range(20)]
            rows = load_incidents(root)

        self.assertEqual(results.count(True), 1)
        self.assertEqual(len(rows), 1)

    def test_rapid_repeated_server_restarts_do_not_flood_incidents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "server.py"
            script.write_text("raise RuntimeError('restart crash')\n", encoding="utf-8")
            command = f'"{sys.executable}" "{script}"'

            with redirect_stdout(io.StringIO()):
                start_daemon(command, cwd=str(root), restart_delay=0, max_runs=5)

            rows = load_incidents(root)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["error_type"], "RuntimeError")

    def test_watch_stability_with_noisy_mixed_stdout_stderr(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "noisy.py"
            script.write_text(
                "import sys\n"
                "print('server ready café')\n"
                "print('GET /health 200')\n"
                "sys.stderr.write('Traceback (most recent call last):\\n')\n"
                "sys.stderr.write('  File \"noisy.py\", line 7, in <module>\\n')\n"
                "sys.stderr.write('    missing_name\\n')\n"
                "sys.stderr.write(\"NameError: name 'missing_name' is not defined\\n\")\n"
                "sys.exit(1)\n",
                encoding="utf-8",
            )
            watcher = TerminalWatcher(f'"{sys.executable}" "{script}"', cwd=str(root), auto_fix=False, verbose=False)

            with patch("agent.terminal_watcher.show_output") as show_output, redirect_stdout(io.StringIO()):
                result = watcher.watch()

            rows = load_incidents(root)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(show_output.call_count, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["error_type"], "NameError")


if __name__ == "__main__":
    unittest.main()
