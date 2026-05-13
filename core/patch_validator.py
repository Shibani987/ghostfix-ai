from __future__ import annotations

import py_compile
import re
import ast
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from core.autofix import create_backup


BLOCKED_FILE_NAMES = {".env", ".env.local", ".env.production", "secrets.json"}
BLOCKED_PARTS = {"secrets", ".git", "__pycache__"}


@dataclass
class PatchValidationResult:
    ok: bool
    reason: str
    rollback_metadata: dict | None = None


class PatchValidator:
    """Validate and apply a proposed local patch block."""

    def validate(self, safe_block: Optional[Dict]) -> PatchValidationResult:
        if not safe_block or not safe_block.get("available"):
            return PatchValidationResult(False, "No safe patch block is available.")

        file_path = Path(safe_block.get("file_path", ""))
        if not file_path.exists():
            return PatchValidationResult(False, "Patch target does not exist.")
        if file_path.name in BLOCKED_FILE_NAMES or any(part in BLOCKED_PARTS for part in file_path.parts):
            return PatchValidationResult(False, "Patch target is blocked by safety policy.")
        if file_path.suffix != ".py":
            return PatchValidationResult(False, "Auto-apply is limited to Python files.")

        start_line = safe_block.get("start_line")
        end_line = safe_block.get("end_line")
        if not isinstance(start_line, int) or not isinstance(end_line, int) or start_line < 1 or end_line < start_line:
            return PatchValidationResult(False, "Patch line range is invalid.")

        old_text = file_path.read_text(encoding="utf-8")
        old_lines = old_text.splitlines(keepends=True)
        if end_line > len(old_lines):
            return PatchValidationResult(False, "Patch line range is outside the target file.")

        if self._looks_dangerous(safe_block.get("replacement", "")):
            return PatchValidationResult(False, "Patch contains dangerous shell/file operation text.")

        changed_lines = end_line - start_line + 1
        replacement_lines = len((safe_block.get("replacement") or "").splitlines())
        if changed_lines > 20 or replacement_lines > 40:
            return PatchValidationResult(False, "Patch is too broad for auto-apply.")

        sandbox = self._validate_in_sandbox(file_path, old_text, old_lines, safe_block)
        if not sandbox.ok:
            return sandbox

        return PatchValidationResult(True, "Patch passes sandbox safety validation.", sandbox.rollback_metadata)

    def apply_with_backup_and_compile(self, safe_block: Dict) -> Dict:
        validation = self.validate(safe_block)
        if not validation.ok:
            return {
                "applied": False,
                "reason": validation.reason,
                "rollback_metadata": validation.rollback_metadata or {},
            }

        file_path = Path(safe_block["file_path"])
        old_text = file_path.read_text(encoding="utf-8")
        old_lines = old_text.splitlines(keepends=True)
        backup_path = create_backup(str(file_path))

        new_lines = old_lines[:]
        replacement = safe_block.get("replacement", "")
        new_lines[safe_block["start_line"] - 1:safe_block["end_line"]] = replacement.splitlines(keepends=True)
        file_path.write_text("".join(new_lines), encoding="utf-8")

        try:
            py_compile.compile(str(file_path), doraise=True)
        except py_compile.PyCompileError as exc:
            file_path.write_text(old_text, encoding="utf-8")
            return {
                "applied": False,
                "backup": str(backup_path),
                "reason": f"Syntax check failed; original file restored. {exc.msg}",
                "rollback_metadata": {
                    "backup": str(backup_path),
                    "restored_original": True,
                    "sandbox_validated": True,
                },
            }

        return {
            "applied": True,
            "backup": str(backup_path),
            "reason": "Patch applied and python -m py_compile equivalent passed.",
            "patch": safe_block.get("patch", ""),
            "rollback_metadata": {
                "backup": str(backup_path),
                "restored_original": False,
                "sandbox_validated": True,
                "target": str(file_path),
            },
        }

    def _looks_dangerous(self, text: str) -> bool:
        patterns = [
            r"rm\s+-rf",
            r"del\s+/[sq]",
            r"shutil\.rmtree",
            r"os\.remove",
            r"os\.unlink",
            r"subprocess\.",
            r"eval\(",
            r"exec\(",
            r"api[_-]?key\s*=",
            r"password\s*=",
            r"token\s*=",
        ]
        lowered = text.lower()
        return any(re.search(pattern, lowered) for pattern in patterns)

    def _validate_in_sandbox(self, file_path: Path, old_text: str, old_lines: list[str], safe_block: Dict) -> PatchValidationResult:
        new_lines = old_lines[:]
        replacement = safe_block.get("replacement", "")
        start_line = safe_block["start_line"]
        end_line = safe_block["end_line"]
        new_lines[start_line - 1:end_line] = replacement.splitlines(keepends=True)

        prefix = old_lines[:start_line - 1]
        suffix = old_lines[end_line:]
        new_suffix_start = len(new_lines) - len(suffix)
        if new_lines[:len(prefix)] != prefix or new_lines[new_suffix_start:] != suffix:
            return PatchValidationResult(False, "Patch changes unrelated lines and requires manual review.")

        new_text = "".join(new_lines)
        try:
            ast.parse(new_text, filename=str(file_path))
            compile(new_text, str(file_path), "exec")
        except SyntaxError as exc:
            return PatchValidationResult(
                False,
                f"Sandbox validation failed: {exc.msg}",
                {"sandbox_validated": False, "target": str(file_path)},
            )

        with tempfile.TemporaryDirectory(prefix="ghostfix_patch_") as temp_dir:
            sandbox_file = Path(temp_dir) / file_path.name
            sandbox_file.write_text(old_text, encoding="utf-8")
            sandbox_file.write_text(new_text, encoding="utf-8")
            try:
                py_compile.compile(str(sandbox_file), doraise=True)
            except py_compile.PyCompileError as exc:
                return PatchValidationResult(
                    False,
                    f"Sandbox compile failed: {exc.msg}",
                    {"sandbox_validated": False, "target": str(file_path)},
                )

        return PatchValidationResult(
            True,
            "Sandbox validation passed.",
            {
                "sandbox_validated": True,
                "sandbox_strategy": "temporary_copy_ast_parse_compile",
                "target": str(file_path),
            },
        )
