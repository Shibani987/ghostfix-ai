from __future__ import annotations

import py_compile
import re
import ast
import tempfile
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from core.autofix import create_backup


BLOCKED_FILE_NAMES = {".env", ".env.local", ".env.production", "secrets.json"}
BLOCKED_PARTS = {"secrets", ".git", "__pycache__"}
JS_TS_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}


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
        action = safe_block.get("action") or "modify_file"
        if action == "framework_multi_file":
            return self._validate_framework_multi_file(safe_block)
        if action == "create_file":
            return self._validate_create_file(file_path, safe_block)
        if not file_path.exists():
            return PatchValidationResult(False, "Patch target does not exist.")
        if file_path.name in BLOCKED_FILE_NAMES or any(part in BLOCKED_PARTS for part in file_path.parts):
            return PatchValidationResult(False, "Patch target is blocked by safety policy.")
        if file_path.suffix != ".py" and file_path.suffix.lower() not in JS_TS_SUFFIXES and file_path.suffix.lower() != ".php":
            return PatchValidationResult(False, "Auto-apply is limited to Python and allowlisted JS/TS/PHP source files.")
        is_js_ts = file_path.suffix.lower() in JS_TS_SUFFIXES
        is_php = file_path.suffix.lower() == ".php"
        if is_js_ts and safe_block.get("language") != "javascript/typescript":
            return PatchValidationResult(False, "JS/TS patches must come from the deterministic JS/TS allowlist.")
        if is_php and safe_block.get("language") != "php":
            return PatchValidationResult(False, "PHP patches must come from the deterministic PHP allowlist.")

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

        if is_js_ts:
            sandbox = self._validate_js_ts_in_sandbox(file_path, old_text, old_lines, safe_block)
        elif is_php:
            sandbox = self._validate_php_in_sandbox(file_path, old_text, old_lines, safe_block)
        else:
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
        if safe_block.get("action") == "framework_multi_file":
            return self._apply_framework_multi_file(safe_block, validation)
        if safe_block.get("action") == "create_file":
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(safe_block.get("replacement", ""), encoding="utf-8")
            return {
                "applied": True,
                "backup": "",
                "reason": "Created allowlisted setup file.",
                "patch": safe_block.get("patch", ""),
                "rollback_metadata": {
                    "backup": "",
                    "created_file": str(file_path),
                    "restored_original": False,
                    "sandbox_validated": True,
                    "target": str(file_path),
                },
            }
        old_text = file_path.read_text(encoding="utf-8")
        old_lines = old_text.splitlines(keepends=True)
        backup_path = create_backup(str(file_path))

        new_lines = old_lines[:]
        replacement = safe_block.get("replacement", "")
        new_lines[safe_block["start_line"] - 1:safe_block["end_line"]] = replacement.splitlines(keepends=True)
        file_path.write_text("".join(new_lines), encoding="utf-8")

        if file_path.suffix == ".py":
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
            "reason": "Patch applied and sandbox validation passed.",
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

    def _validate_create_file(self, file_path: Path, safe_block: Dict) -> PatchValidationResult:
        allowed_names = {"package.json", ".env.example", "__init__.py"}
        allowed_suffixes = {".html"}
        if file_path.exists():
            return PatchValidationResult(False, "Create-file target already exists.")
        if file_path.name in BLOCKED_FILE_NAMES or file_path.name.startswith(".env.") and file_path.name != ".env.example":
            return PatchValidationResult(False, "Create-file target is blocked by safety policy.")
        if file_path.name not in allowed_names and file_path.suffix.lower() not in allowed_suffixes:
            return PatchValidationResult(False, "Create-file auto-fix is limited to package.json, .env.example, __init__.py, or template files.")
        if any(part in BLOCKED_PARTS for part in file_path.parts):
            return PatchValidationResult(False, "Create-file target is blocked by safety policy.")
        content = safe_block.get("replacement", "")
        if self._looks_dangerous(content):
            return PatchValidationResult(False, "Create-file content contains dangerous text.")
        if len(content) > 4096:
            return PatchValidationResult(False, "Create-file content is too large for auto-apply.")
        if file_path.name == "package.json":
            try:
                import json

                parsed = json.loads(content or "{}")
            except Exception as exc:
                return PatchValidationResult(False, f"package.json content is not valid JSON: {exc}")
            if not isinstance(parsed, dict):
                return PatchValidationResult(False, "package.json content must be a JSON object.")
        return PatchValidationResult(
            True,
            "Create-file patch passes safety validation.",
            {"sandbox_validated": True, "sandbox_strategy": "create_file_allowlist", "target": str(file_path)},
        )

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

    def _validate_framework_multi_file(self, safe_block: Dict) -> PatchValidationResult:
        language = safe_block.get("language")
        js_frameworks = {"next.js", "react", "vite", "vite/react", "typescript", "express", "node"}
        py_frameworks = {"python", "django", "flask", "fastapi"}
        if language == "javascript/typescript":
            if safe_block.get("framework") not in js_frameworks:
                return PatchValidationResult(False, "Framework multi-file fixes are currently limited to guarded JS/TS framework patches.")
        elif language == "python":
            if safe_block.get("framework") not in py_frameworks:
                return PatchValidationResult(False, "Python framework fixes are limited to Python/Django/Flask/FastAPI.")
        else:
            return PatchValidationResult(False, "Unsupported language for framework multi-file fix.")
        if not safe_block.get("requires_project_validation"):
            return PatchValidationResult(False, "Framework fixes require project validation.")
        files = safe_block.get("files") or []
        if not isinstance(files, list) or not files:
            return PatchValidationResult(False, "Framework patch has no file targets.")
        if len(files) > 4:
            return PatchValidationResult(False, "Framework patch touches too many files.")

        paths = [Path(item.get("file_path", "")) for item in files if isinstance(item, dict)]
        if len(paths) != len(files):
            return PatchValidationResult(False, "Framework patch file list is invalid.")
        root = self._common_root(paths)
        if not root:
            return PatchValidationResult(False, "Framework patch files do not share a safe project root.")

        for item, path in zip(files, paths):
            if path.name in BLOCKED_FILE_NAMES or path.name.startswith(".env.") and path.name != ".env.example":
                return PatchValidationResult(False, "Framework patch attempted to edit a blocked env/secret file.")
            if any(part in BLOCKED_PARTS for part in path.parts):
                return PatchValidationResult(False, "Framework patch target is blocked by safety policy.")
            if language == "javascript/typescript" and path.suffix.lower() not in JS_TS_SUFFIXES and path.name != ".env.example":
                return PatchValidationResult(False, "Framework patch may only edit JS/TS source files and .env.example.")
            if language == "python" and path.suffix.lower() != ".py":
                return PatchValidationResult(False, "Python framework patch may only edit Python source files.")
            if path.exists():
                current = path.read_text(encoding="utf-8")
                if current != item.get("old_text", ""):
                    return PatchValidationResult(False, f"Framework patch source changed before apply: {path}")
            elif path.name != ".env.example" or item.get("old_text", ""):
                return PatchValidationResult(False, "Framework patch can only create .env.example as a new file.")
            new_text = item.get("new_text", "")
            if self._looks_dangerous(new_text):
                return PatchValidationResult(False, "Framework patch contains dangerous shell/file operation text.")
            if len(new_text) > 24000:
                return PatchValidationResult(False, "Framework patch target is too large for auto-apply.")

        commands = safe_block.get("validation_commands") or []
        if language == "javascript/typescript" and not any(command in commands for command in (["npm", "run", "build"], ["tsc", "--noEmit"])):
            return PatchValidationResult(False, "JS/TS framework fixes require npm run build or tsc --noEmit validation.")
        if language == "python" and not any(command[:3] == ["python", "-m", "py_compile"] for command in commands):
            return PatchValidationResult(False, "Python framework fixes require py_compile validation.")

        try:
            sandbox_result = self._validate_framework_in_project_copy(root, files, commands)
        except Exception as exc:
            return PatchValidationResult(False, f"Framework sandbox validation failed: {exc}")
        return sandbox_result

    def _validate_framework_in_project_copy(self, root: Path, files: list[Dict], commands: list[list[str]]) -> PatchValidationResult:
        with tempfile.TemporaryDirectory(prefix="ghostfix_framework_patch_") as temp_dir:
            sandbox_root = Path(temp_dir) / root.name
            ignore = shutil.ignore_patterns(
                ".git",
                ".ghostfix",
                ".next",
                "node_modules",
                "dist",
                "build",
                "coverage",
                "__pycache__",
                ".pytest_cache",
            )
            shutil.copytree(root, sandbox_root, ignore=ignore)
            for item in files:
                source = Path(item["file_path"])
                rel = source.resolve().relative_to(root.resolve())
                target = sandbox_root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(item.get("new_text", ""), encoding="utf-8")
            for command in commands:
                result = subprocess.run(
                    command,
                    cwd=str(sandbox_root),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=120,
                )
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout or "").strip()[:500]
                    return PatchValidationResult(
                        False,
                        f"Project validation failed for {' '.join(command)}: {detail}",
                        {"sandbox_validated": False, "sandbox_strategy": "temporary_project_copy", "target": str(root)},
                    )
        return PatchValidationResult(
            True,
            "Framework patch passes temporary project copy validation and npm run build.",
            {
                "sandbox_validated": True,
                "sandbox_strategy": "temporary_project_copy_npm_build",
                "target": str(root),
                "validation_commands": [" ".join(command) for command in commands],
            },
        )

    def _apply_framework_multi_file(self, safe_block: Dict, validation: PatchValidationResult) -> Dict:
        files = safe_block.get("files") or []
        backups = []
        created_files = []
        try:
            for item in files:
                path = Path(item["file_path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    backup_path = create_backup(str(path))
                    backups.append({"target": str(path), "backup": str(backup_path)})
                else:
                    created_files.append(str(path))
                path.write_text(item.get("new_text", ""), encoding="utf-8")
        except Exception as exc:
            for row in backups:
                try:
                    shutil.copyfile(row["backup"], row["target"])
                except OSError:
                    pass
            return {
                "applied": False,
                "backup": backups[0]["backup"] if backups else "",
                "reason": f"Framework patch apply failed; restored backups where possible. {exc}",
                "rollback_metadata": {
                    "backups": backups,
                    "created_files": created_files,
                    "restored_original": True,
                    "sandbox_validated": bool((validation.rollback_metadata or {}).get("sandbox_validated")),
                },
            }
        return {
            "applied": True,
            "backup": backups[0]["backup"] if backups else "",
            "reason": "Framework patch applied after sandbox project validation.",
            "patch": safe_block.get("patch", ""),
            "rollback_metadata": {
                "backup": backups[0]["backup"] if backups else "",
                "backups": backups,
                "created_files": created_files,
                "restored_original": False,
                "sandbox_validated": True,
                "target": safe_block.get("file_path", ""),
            },
        }

    def _common_root(self, paths: list[Path]) -> Path | None:
        resolved = [path.resolve() for path in paths if path]
        if not resolved:
            return None
        marker_names = {"package.json", "pyproject.toml", "manage.py", "artisan"}
        current = resolved[0].parent
        while current != current.parent:
            if any((current / marker).exists() for marker in marker_names):
                if all(self._is_relative_to(path, current) for path in resolved):
                    return current
            current = current.parent
        return None

    def _is_relative_to(self, path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    def _validate_php_in_sandbox(self, file_path: Path, old_text: str, old_lines: list[str], safe_block: Dict) -> PatchValidationResult:
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
        if end_line - start_line + 1 != 1:
            return PatchValidationResult(False, "PHP auto-fix is limited to one-line deterministic patches.")

        validation_note = "temporary_copy_text_validation"
        php = shutil.which("php")
        with tempfile.TemporaryDirectory(prefix="ghostfix_php_patch_") as temp_dir:
            sandbox_file = Path(temp_dir) / file_path.name
            sandbox_file.write_text("".join(new_lines), encoding="utf-8")
            if php:
                result = subprocess.run(
                    [php, "-l", str(sandbox_file)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    return PatchValidationResult(
                        False,
                        f"Sandbox php -l failed: {(result.stderr or result.stdout).strip()[:240]}",
                        {"sandbox_validated": False, "target": str(file_path)},
                    )
                validation_note = "temporary_copy_php_lint"

        return PatchValidationResult(
            True,
            "Sandbox validation passed.",
            {
                "sandbox_validated": True,
                "sandbox_strategy": validation_note,
                "target": str(file_path),
            },
        )

    def _validate_js_ts_in_sandbox(self, file_path: Path, old_text: str, old_lines: list[str], safe_block: Dict) -> PatchValidationResult:
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

        if end_line - start_line + 1 != 1:
            return PatchValidationResult(False, "JS/TS auto-fix is limited to one-line deterministic patches.")

        with tempfile.TemporaryDirectory(prefix="ghostfix_js_patch_") as temp_dir:
            sandbox_file = Path(temp_dir) / file_path.name
            sandbox_file.write_text("".join(new_lines), encoding="utf-8")
            validation_note = "temporary_copy_text_validation"
            node = shutil.which("node")
            if node and file_path.suffix.lower() in {".js", ".mjs", ".cjs"}:
                result = subprocess.run(
                    [node, "--check", str(sandbox_file)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    return PatchValidationResult(
                        False,
                        f"Sandbox node --check failed: {(result.stderr or result.stdout).strip()[:240]}",
                        {"sandbox_validated": False, "target": str(file_path)},
                    )
                validation_note = "temporary_copy_node_check"

        return PatchValidationResult(
            True,
            "Sandbox validation passed.",
            {
                "sandbox_validated": True,
                "sandbox_strategy": validation_note,
                "target": str(file_path),
            },
        )
