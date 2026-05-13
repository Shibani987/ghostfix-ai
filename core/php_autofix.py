from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path


SENSITIVE_PARTS = {"auth", "login", "oauth", "session", "payment", "billing", "database", "db", "security", "secret", "config"}


@dataclass
class PhpPatchPlan:
    available: bool
    reason: str
    file_path: str = ""
    start_line: int = 0
    end_line: int = 0
    replacement: str = ""
    preview: str = ""
    validation: str = ""


def build_php_patch_plan(diagnostic: dict, cwd: str | None = None) -> PhpPatchPlan:
    if diagnostic.get("root_cause") != "php_parse_error":
        return PhpPatchPlan(False, "PHP auto-fix is limited to simple parse errors.")
    path = _resolve_file(diagnostic.get("file") or "", cwd)
    if not path:
        return PhpPatchPlan(False, "No exact local PHP target file was found.")
    if path.suffix.lower() != ".php":
        return PhpPatchPlan(False, "Target is not a PHP source file.")
    if _is_sensitive_path(path):
        return PhpPatchPlan(False, "PHP auto-fix is blocked for config, auth, database, payment, security, or secret-sensitive paths.")
    line_no = int(diagnostic.get("line") or 0)
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        return PhpPatchPlan(False, f"Could not read target file: {exc}")
    if line_no < 1 or line_no > len(lines):
        return PhpPatchPlan(False, "No exact PHP line was available for repair.")
    line = lines[line_no - 1]
    stripped = line.rstrip("\r\n")
    if not stripped.strip() or stripped.rstrip().endswith((";", "{", "}", ":", "?>")):
        return PhpPatchPlan(False, "Line does not look like a missing-semicolon PHP repair.")
    if not re.search(r"(\$[A-Za-z_]\w*\s*=|echo\s+|return\s+)", stripped):
        return PhpPatchPlan(False, "PHP parse repair is not a simple assignment/echo/return line.")
    replacement = stripped.rstrip() + ";" + _line_ending(line)
    new_lines = lines[:]
    new_lines[line_no - 1:line_no] = replacement.splitlines(keepends=True)
    return PhpPatchPlan(
        True,
        "Safe PHP missing-semicolon patch preview can be applied.",
        file_path=str(path),
        start_line=line_no,
        end_line=line_no,
        replacement=replacement,
        preview=_diff_preview(path, lines, new_lines),
        validation="single-line deterministic PHP patch preview",
    )


def patch_block_from_plan(plan: PhpPatchPlan) -> dict:
    return {
        "available": plan.available,
        "reason": plan.reason,
        "file_path": plan.file_path,
        "start_line": plan.start_line,
        "end_line": plan.end_line,
        "replacement": plan.replacement,
        "patch": plan.preview,
        "validation": plan.validation,
        "language": "php",
    }


def _resolve_file(value: str, cwd: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = Path(cwd or ".") / path
    try:
        path = path.resolve()
    except OSError:
        return None
    return path if path.exists() and path.is_file() else None


def _is_sensitive_path(path: Path) -> bool:
    lowered = [part.lower() for part in path.parts]
    return any(part in SENSITIVE_PARTS or any(token in part for token in SENSITIVE_PARTS) for part in lowered)


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return ""


def _diff_preview(path: Path, old_lines: list[str], new_lines: list[str]) -> str:
    return "".join(
        difflib.unified_diff(
            [line if line.endswith("\n") else f"{line}\n" for line in old_lines],
            [line if line.endswith("\n") else f"{line}\n" for line in new_lines],
            fromfile=str(path),
            tofile=str(path),
            lineterm="\n",
        )
    )
