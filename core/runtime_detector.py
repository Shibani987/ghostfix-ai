from __future__ import annotations

from core.language_diagnostics import detect_language


def classify_runtime(command: str = "", output: str = "", file_path: str | None = None) -> str:
    """Classify runtime logs into GhostFix watch-mode language buckets."""
    return detect_language(command=command, output=output, file_path=file_path)
