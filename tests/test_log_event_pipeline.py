from __future__ import annotations

import unittest

from core.log_events import LogEventKind, LogEventPipeline, LogSourceType
from core.parser import extract_runtime_error, parse_error


class LogEventPipelineTests(unittest.TestCase):
    def test_noisy_logs_group_python_traceback(self):
        pipeline = LogEventPipeline()

        events = []
        for line in [
            "INFO booting\n",
            "DEBUG still fine\n",
            "Traceback (most recent call last):\n",
            "  File \"app.py\", line 2, in <module>\n",
            "    missing\n",
            "NameError: name 'missing' is not defined\n",
            "INFO restarted\n",
        ]:
            events.extend(pipeline.feed(line))

        blocks = [event for event in events if event.kind == LogEventKind.PYTHON_TRACEBACK]
        self.assertEqual(len(blocks), 1)
        self.assertIn("NameError", blocks[0].text)
        self.assertEqual(blocks[0].source_type, LogSourceType.SUBPROCESS)

    def test_partial_traceback_chunks_are_buffered(self):
        pipeline = LogEventPipeline()

        events = []
        events.extend(pipeline.feed("Traceback (most recent"))
        events.extend(pipeline.feed(" call last):\n  File \"app.py\", line 1, in <module>\n"))
        events.extend(pipeline.feed("    boom\nRuntime"))
        events.extend(pipeline.feed("Error: broken"))
        events.extend(pipeline.flush())

        blocks = [event for event in events if event.kind == LogEventKind.PYTHON_TRACEBACK]
        self.assertEqual(len(blocks), 1)
        self.assertIn("RuntimeError: broken", blocks[0].text)

    def test_repeated_errors_are_grouped_as_separate_events(self):
        pipeline = LogEventPipeline()
        traceback = (
            "Traceback (most recent call last):\n"
            "  File \"app.py\", line 1, in <module>\n"
            "    boom\n"
            "RuntimeError: broken\n"
        )

        events = pipeline.feed(traceback) + pipeline.feed(traceback)

        self.assertEqual(
            [event.kind for event in events].count(LogEventKind.PYTHON_TRACEBACK),
            2,
        )

    def test_huge_logs_are_bounded(self):
        pipeline = LogEventPipeline(max_buffer_size=2048, max_event_size=512)
        huge_line = "x" * 10_000 + "\n"

        events = pipeline.feed(huge_line)

        self.assertLessEqual(len(pipeline.buffered_text()), 2048)
        self.assertTrue(any(event.truncated for event in events))
        self.assertLessEqual(max(len(event.text) for event in events), 512)

    def test_unicode_bytes_are_replaced_not_crashing(self):
        pipeline = LogEventPipeline()

        events = pipeline.feed(b"bad utf8 \xff\xfe\n")

        self.assertEqual(events[0].kind, LogEventKind.LINE)
        self.assertIn("\ufffd", events[0].text)

    def test_file_and_docker_source_types(self):
        file_pipeline = LogEventPipeline(source_type=LogSourceType.FILE)
        docker_pipeline = LogEventPipeline(source_type=LogSourceType.DOCKER)

        file_events = file_pipeline.events_from_file_lines(["ERROR one\n"])
        docker_events = docker_pipeline.events_from_docker_stream([b"ERROR two\n"])

        self.assertEqual(file_events[0].source_type, LogSourceType.FILE)
        self.assertEqual(file_events[0].stream, "file")
        self.assertEqual(docker_events[0].source_type, LogSourceType.DOCKER)
        self.assertEqual(docker_events[0].stream, "docker")

    def test_mixed_stdout_stderr_streams_keep_stream_labels(self):
        pipeline = LogEventPipeline()

        events = []
        events.extend(pipeline.feed("server ready\n", stream="stdout"))
        events.extend(pipeline.feed("Traceback (most recent call last):\n", stream="stderr"))
        events.extend(pipeline.feed("  File \"app.py\", line 1, in <module>\n", stream="stderr"))
        events.extend(pipeline.feed("ValueError: bad\n", stream="stderr"))

        self.assertEqual(events[0].stream, "stdout")
        self.assertTrue(any(event.kind == LogEventKind.PYTHON_TRACEBACK for event in events))

    def test_parser_guards_malformed_input(self):
        self.assertIsNone(extract_runtime_error(object(), command="python app.py"))
        parsed = parse_error(object())
        self.assertEqual(parsed["type"], "UnknownError")


if __name__ == "__main__":
    unittest.main()
