from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Iterable, Optional


class LogSourceType(str, Enum):
    SUBPROCESS = "subprocess"
    FILE = "file"
    DOCKER = "docker"


class LogEventKind(str, Enum):
    LINE = "line"
    PYTHON_TRACEBACK = "python_traceback"
    ERROR_BLOCK = "error_block"
    BUFFER_TRUNCATED = "buffer_truncated"
    MALFORMED = "malformed"


@dataclass
class LogEvent:
    source_type: LogSourceType
    stream: str
    text: str
    kind: LogEventKind = LogEventKind.LINE
    timestamp: float = 0.0
    truncated: bool = False

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.time()


class LogEventPipeline:
    """Bounded streaming log pipeline for noisy local developer processes."""

    def __init__(
        self,
        *,
        source_type: LogSourceType = LogSourceType.SUBPROCESS,
        max_buffer_size: int = 128_000,
        max_event_size: int = 32_000,
        max_traceback_size: int = 64_000,
        max_partial_size: int = 16_000,
        timeout_seconds: float = 30.0,
    ):
        self.source_type = source_type
        self.max_buffer_size = max(1024, int(max_buffer_size))
        self.max_event_size = max(256, int(max_event_size))
        self.max_traceback_size = max(self.max_event_size, int(max_traceback_size))
        self.max_partial_size = max(1, int(max_partial_size))
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self._recent: Deque[str] = deque()
        self._recent_size = 0
        self._traceback_lines: list[str] = []
        self._traceback_size = 0
        self._traceback_started_at: Optional[float] = None
        self._partial_line = ""

    def feed(self, text: str | bytes, *, stream: str = "stdout") -> list[LogEvent]:
        events: list[LogEvent] = []
        safe_text = self._partial_line + self._coerce_text(text)
        self._partial_line = ""
        if safe_text and not safe_text.endswith(("\n", "\r")):
            lines = safe_text.splitlines(keepends=True)
            if lines:
                self._partial_line = lines.pop()
                if len(self._partial_line) > self.max_partial_size:
                    self._partial_line = self._partial_line[-self.max_partial_size:]
            else:
                self._partial_line = safe_text
                if len(self._partial_line) > self.max_partial_size:
                    self._partial_line = self._partial_line[-self.max_partial_size:]
                lines = []
        else:
            lines = safe_text.splitlines(keepends=True)
        for raw_line in lines:
            if not raw_line:
                continue
            line, truncated = self._limit_event(raw_line)
            self._append_recent(line)
            line_event = LogEvent(
                source_type=self.source_type,
                stream=stream,
                text=line,
                kind=LogEventKind.LINE,
                truncated=truncated,
            )
            events.append(line_event)
            grouped = self._feed_grouping(line_event)
            if grouped:
                events.append(grouped)
        expired = self._flush_if_timed_out()
        if expired:
            events.append(expired)
        return events

    def flush(self) -> list[LogEvent]:
        events: list[LogEvent] = []
        if self._partial_line:
            partial = self._partial_line
            self._partial_line = ""
            events.extend(self.feed(partial + "\n"))
        event = self._flush_traceback()
        if event:
            events.append(event)
        return events

    def buffered_text(self) -> str:
        return "".join(self._recent)

    def events_from_file_lines(self, lines: Iterable[str]) -> list[LogEvent]:
        events: list[LogEvent] = []
        for line in lines:
            events.extend(self.feed(line, stream="file"))
        events.extend(self.flush())
        return events

    def events_from_docker_stream(self, chunks: Iterable[str | bytes]) -> list[LogEvent]:
        events: list[LogEvent] = []
        for chunk in chunks:
            events.extend(self.feed(chunk, stream="docker"))
        events.extend(self.flush())
        return events

    def _feed_grouping(self, event: LogEvent) -> Optional[LogEvent]:
        line = event.text
        stripped = line.strip()
        if line.lstrip().startswith("Traceback (most recent call last):"):
            self._traceback_lines = [line]
            self._traceback_size = len(line)
            self._traceback_started_at = event.timestamp
            return None
        if not self._traceback_lines and line.lstrip().startswith('File "'):
            self._traceback_lines = [line]
            self._traceback_size = len(line)
            self._traceback_started_at = event.timestamp
            return None
        if not self._traceback_lines:
            return None
        self._traceback_lines.append(line)
        self._traceback_size += len(line)
        while self._traceback_lines and self._traceback_size > self.max_traceback_size:
            removed = self._traceback_lines.pop(0)
            self._traceback_size -= len(removed)
        if self._is_python_exception_line(stripped):
            return self._flush_traceback()
        return None

    def _flush_traceback(self) -> Optional[LogEvent]:
        if not self._traceback_lines:
            return None
        text, truncated = self._limit_event("".join(self._traceback_lines))
        self._traceback_lines = []
        self._traceback_size = 0
        self._traceback_started_at = None
        return LogEvent(
            source_type=self.source_type,
            stream="stderr",
            text=text,
            kind=LogEventKind.PYTHON_TRACEBACK,
            truncated=truncated,
        )

    def _flush_if_timed_out(self) -> Optional[LogEvent]:
        if not self._traceback_lines or self._traceback_started_at is None:
            return None
        if time.time() - self._traceback_started_at < self.timeout_seconds:
            return None
        return self._flush_traceback()

    def _append_recent(self, text: str) -> None:
        self._recent.append(text)
        self._recent_size += len(text)
        while self._recent and self._recent_size > self.max_buffer_size:
            removed = self._recent.popleft()
            self._recent_size -= len(removed)

    def _limit_event(self, text: str) -> tuple[str, bool]:
        if len(text) <= self.max_event_size:
            return text, False
        return text[-self.max_event_size:], True

    def _coerce_text(self, text: str | bytes) -> str:
        try:
            if isinstance(text, bytes):
                return text.decode("utf-8", errors="replace")
            return str(text)
        except Exception:
            return "[malformed log event]\n"

    def _is_python_exception_line(self, stripped: str) -> bool:
        if not stripped:
            return False
        exception_names = {
            "TemplateNotFound",
            "TemplateDoesNotExist",
            "ImproperlyConfigured",
            "HTTPException",
            "OperationalError",
            "ProgrammingError",
            "ValidationError",
            "KeyboardInterrupt",
            "SystemExit",
        }
        name = stripped.split(":", 1)[0].rsplit(".", 1)[-1]
        if stripped.startswith(("File ", "~", "^", "raise ", "return ", "print(", "import ", "from ")):
            return False
        return (
            stripped.endswith(("Error", "Exception", "Warning"))
            or "Error:" in stripped
            or "Exception:" in stripped
            or name in exception_names
            or stripped.startswith(("KeyboardInterrupt", "SystemExit"))
            or "ImproperlyConfigured:" in stripped
        )
