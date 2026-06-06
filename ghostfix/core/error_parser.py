"""
ErrorParser
Detects errors from any language's output stream and extracts
file, line number, error type, and full traceback.
"""
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedError:
    raw: str
    language: str = "unknown"
    error_type: str = "Error"
    error_message: str = ""
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    traceback_lines: list[str] = field(default_factory=list)
    all_files: list[tuple[str, int]] = field(default_factory=list)  # (file, line)


# ── Language detection patterns ──────────────────────────────────────────────
LANG_SIGNALS = {
    "python": [
        r"Traceback \(most recent call last\)",
        r"File \".*\.py\", line \d+",
        r"\w+Error:",
        r"django\.",
        r"flask\.",
    ],
    "nodejs": [
        r"at .+ \(.+\.(?:js|ts|mjs):\d+:\d+\)",
        r"TypeError:|ReferenceError:|SyntaxError:|RangeError:",
        r"Error: Cannot find module",
        r"UnhandledPromiseRejection",
    ],
    "java": [
        r"Exception in thread",
        r"at com\.|at org\.|at java\.",
        r"\.java:\d+\)",
        r"java\.lang\.",
    ],
    "go": [
        r"goroutine \d+ \[",
        r"panic:",
        r"\.go:\d+",
        r"runtime error:",
    ],
    "rust": [
        r"thread '.*' panicked",
        r"error\[E\d+\]",
        r"\.rs:\d+",
    ],
    "ruby": [
        r"\.rb:\d+:in `",
        r"NameError:|NoMethodError:|RuntimeError:",
    ],
}

# ── Per-language file+line extractors ────────────────────────────────────────
FILE_LINE_PATTERNS = {
    "python": re.compile(r'File "([^"]+)", line (\d+)'),
    "nodejs": re.compile(r'at .+? \(([^)]+\.(?:js|ts|mjs|cjs)):(\d+):\d+\)'),
    "java":   re.compile(r'at [\w.$]+\((\w+\.java):(\d+)\)'),
    "go":     re.compile(r'([\w./]+\.go):(\d+)'),
    "rust":   re.compile(r'([\w./]+\.rs):(\d+)'),
    "ruby":   re.compile(r'([\w./]+\.rb):(\d+)'),
    "generic": re.compile(r'([\w./_-]+\.\w{1,6})[: ](\d+)'),
}

ERROR_TYPE_PATTERNS = {
    "python": re.compile(r'^(\w+(?:Error|Exception|Warning|Fault)):\s*(.+)$', re.MULTILINE),
    "nodejs": re.compile(r'^(TypeError|ReferenceError|SyntaxError|RangeError|Error):\s*(.+)$', re.MULTILINE),
    "java":   re.compile(r'(java\.[\w.]+(?:Exception|Error))(?::\s*(.+))?'),
    "go":     re.compile(r'panic:\s*(.+)'),
    "rust":   re.compile(r"thread '.*' panicked at '(.+)'"),
    "generic":re.compile(r'(?:error|Error|ERROR):\s*(.+)'),
}

# Lines containing these words signal the start of an error block
ERROR_SIGNAL_WORDS = [
    "traceback", "exception", "error:", "panic:", "fatal:",
    "unhandled", "segfault", "core dumped", "traceback (most",
    "syntaxerror", "typeerror", "valueerror", "attributeerror",
    "nameerror", "importerror", "runtimeerror", "keyerror",
    "indexerror", "oserror", "ioerror", "filenotfounderror",
    "permissionerror", "connectionerror", "timeouterror",
    "nullpointerexception", "outofmemoryerror",
    "cannot read propert", "is not defined", "is not a function",
    "module not found", "cannot find module",
    "goroutine", "panicked at",
    "thread 'main' panicked",
]


class ErrorParser:

    def is_error_signal(self, line: str) -> bool:
        lower = line.lower()
        return any(sig in lower for sig in ERROR_SIGNAL_WORDS)

    def detect_language(self, text: str) -> str:
        scores = {lang: 0 for lang in LANG_SIGNALS}
        for lang, patterns in LANG_SIGNALS.items():
            for pat in patterns:
                if re.search(pat, text, re.IGNORECASE):
                    scores[lang] += 1
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "generic"

    def parse(self, raw: str) -> ParsedError:
        lang = self.detect_language(raw)
        result = ParsedError(raw=raw, language=lang)
        result.traceback_lines = raw.splitlines()

        # Extract error type + message
        pat = ERROR_TYPE_PATTERNS.get(lang) or ERROR_TYPE_PATTERNS["generic"]
        m = pat.search(raw)
        if m:
            result.error_type = m.group(1).strip() if m.lastindex >= 1 else "Error"
            result.error_message = (m.group(2).strip() if m.lastindex >= 2 else "").strip()

        # Extract all file+line mentions
        file_pat = FILE_LINE_PATTERNS.get(lang) or FILE_LINE_PATTERNS["generic"]
        seen = set()
        for fm in file_pat.finditer(raw):
            fp, ln = fm.group(1), int(fm.group(2))
            # Skip stdlib / vendor paths
            if any(skip in fp for skip in [
                "site-packages", "lib/python", "node_modules",
                "<frozen", "<stdin>", "/usr/", "dist-packages",
            ]):
                continue
            key = (fp, ln)
            if key not in seen:
                result.all_files.append((fp, ln))
                seen.add(key)

        # Primary file = last user file in traceback (most specific)
        if result.all_files:
            result.file_path, result.line_number = result.all_files[-1]

        return result
