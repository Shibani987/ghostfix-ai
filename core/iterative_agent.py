from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.language_diagnostics import diagnose_non_python
from core.repo_engine import build_repo_snapshot, compute_confidence, is_sensitive_target
from core.runtime_detector import infer_runtime_profile


MAX_RETRIES = 2
SUPPORTED_FRAMEWORKS = {"python", "django", "flask", "fastapi", "express", "node", "next.js", "react", "vite", "vite/react", "typescript"}


@dataclass
class RetryTelemetry:
    attempt: int
    error_type: str
    root_cause: str
    confidence: int
    validation_command: str
    validation_passed: bool
    duplicate_failure: bool = False
    regression_detected: bool = False
    stopped_reason: str = ""


@dataclass
class IterativeValidationResult:
    ok: bool
    reason: str
    patch_block: dict[str, Any] = field(default_factory=dict)
    telemetry: list[RetryTelemetry] = field(default_factory=list)
    confidence: int = 0
    regression_detected: bool = False
    rollback_verified: bool = False
    repo_context_graph: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["telemetry"] = [asdict(item) for item in self.telemetry]
        return payload


def iterative_validate_patch(
    diagnostic: dict[str, Any],
    patch_block: dict[str, Any],
    *,
    command: str = "",
    cwd: str | None = None,
    max_retries: int = MAX_RETRIES,
) -> IterativeValidationResult:
    root = Path(cwd or ".").resolve()
    profile = infer_runtime_profile(command=command, cwd=str(root), output=diagnostic.get("message", ""))
    framework = diagnostic.get("framework") or profile.framework
    if framework not in SUPPORTED_FRAMEWORKS:
        return IterativeValidationResult(False, f"Unsupported framework for iterative validation: {framework}")
    if _has_sensitive_targets(patch_block):
        return IterativeValidationResult(False, "Patch target is blocked by safety policy.")
    commands = _validation_commands(root, command, framework)
    if not commands:
        return IterativeValidationResult(False, "No framework-aware validation command is available.")

    snapshot = build_repo_snapshot(root)
    with tempfile.TemporaryDirectory(prefix="ghostfix_iterative_") as temp_dir:
        sandbox_root = Path(temp_dir) / root.name
        _copy_project(root, sandbox_root)
        changed: dict[str, tuple[str, str]] = {}
        current_block = _rebase_patch_block(patch_block, root, sandbox_root)
        seen_failures: set[str] = set()
        telemetry: list[RetryTelemetry] = []
        baseline_confidence = int(diagnostic.get("confidence") or 0)

        for attempt in range(0, max_retries + 1):
            apply_reason = _apply_patch_to_sandbox(current_block, sandbox_root, changed)
            if apply_reason:
                return IterativeValidationResult(False, apply_reason, telemetry=telemetry, repo_context_graph=_snapshot_payload(snapshot))
            result, command_text = _run_validation(commands, sandbox_root)
            failure_output = f"{result.stdout}\n{result.stderr}"
            if result.returncode == 0:
                final_block = _final_patch_block(patch_block, root, sandbox_root, changed, commands)
                confidence = compute_confidence(
                    validation_success=True,
                    exact_symbol_or_file_match=True,
                    rerun_success=True,
                    framework_confidence=max(baseline_confidence, 75),
                    parser_confidence=max(baseline_confidence, 75),
                    stacktrace_quality=90,
                )
                telemetry.append(
                    RetryTelemetry(
                        attempt=attempt,
                        error_type="none",
                        root_cause="validation_passed",
                        confidence=confidence,
                        validation_command=command_text,
                        validation_passed=True,
                    )
                )
                return IterativeValidationResult(
                    True,
                    "Iterative validation passed.",
                    patch_block=final_block,
                    telemetry=telemetry,
                    confidence=confidence,
                    rollback_verified=_rollback_metadata_complete(final_block),
                    repo_context_graph=_snapshot_payload(snapshot),
                )

            old_disabled = os.environ.get("GHOSTFIX_ITERATIVE_DISABLED")
            os.environ["GHOSTFIX_ITERATIVE_DISABLED"] = "1"
            try:
                next_diagnostic = diagnose_non_python(failure_output, command=command_text or command, cwd=str(sandbox_root))
            finally:
                if old_disabled is None:
                    os.environ.pop("GHOSTFIX_ITERATIVE_DISABLED", None)
                else:
                    os.environ["GHOSTFIX_ITERATIVE_DISABLED"] = old_disabled
            if not next_diagnostic:
                telemetry.append(_telemetry_from_failure(attempt, "UnknownError", "unparsed_validation_failure", 0, command_text, False, stopped_reason="unparsed failure"))
                return IterativeValidationResult(False, "Validation failed with an unparsed error.", telemetry=telemetry, regression_detected=True, repo_context_graph=_snapshot_payload(snapshot))
            failure_key = _failure_key(next_diagnostic)
            duplicate = failure_key in seen_failures
            seen_failures.add(failure_key)
            new_confidence = int(next_diagnostic.get("confidence") or 0)
            regression = _is_regression(diagnostic, next_diagnostic) or new_confidence < max(40, baseline_confidence - 25)
            telemetry.append(
                _telemetry_from_failure(
                    attempt,
                    next_diagnostic.get("error_type", ""),
                    next_diagnostic.get("root_cause", ""),
                    new_confidence,
                    command_text,
                    False,
                    duplicate_failure=duplicate,
                    regression_detected=regression,
                    stopped_reason="duplicate failure" if duplicate else ("confidence drop/regression" if regression else ""),
                )
            )
            if duplicate or regression:
                return IterativeValidationResult(False, "Validation stopped after duplicate failure or regression.", telemetry=telemetry, regression_detected=regression, repo_context_graph=_snapshot_payload(snapshot))
            if attempt >= max_retries:
                return IterativeValidationResult(False, "Validation failed after max retries.", telemetry=telemetry, repo_context_graph=_snapshot_payload(snapshot))
            next_block = next_diagnostic.get("patch_block") or {}
            if not next_block.get("available"):
                return IterativeValidationResult(False, next_diagnostic.get("why_auto_fix_blocked") or "New failure has no deterministic patch.", telemetry=telemetry, repo_context_graph=_snapshot_payload(snapshot))
            if _has_sensitive_targets(next_block):
                return IterativeValidationResult(False, "Retry patch target is blocked by safety policy.", telemetry=telemetry, repo_context_graph=_snapshot_payload(snapshot))
            current_block = _rebase_patch_block(next_block, sandbox_root, sandbox_root)

    return IterativeValidationResult(False, "Unexpected iterative validation exit.", repo_context_graph=_snapshot_payload(snapshot))


def _validation_commands(root: Path, command: str, framework: str) -> list[list[str]]:
    package = _package_json(root)
    scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
    commands: list[list[str]] = []
    if framework in {"next.js", "react", "vite", "vite/react", "typescript", "express", "node"}:
        if "build" in scripts:
            commands.append(["npm", "run", "build"])
        if (root / "tsconfig.json").exists():
            commands.append(["tsc", "--noEmit"])
        if command:
            commands.append(["__shell__", command])
    else:
        target = _python_target_from_command(command)
        if target:
            commands.append(["python", "-m", "py_compile", target])
        if command:
            commands.append(["__shell__", command])
    return commands


def _run_validation(commands: list[list[str]], cwd: Path) -> tuple[subprocess.CompletedProcess, str]:
    last = subprocess.CompletedProcess([], 0, stdout="", stderr="")
    last_text = ""
    for command in commands:
        if command and command[0] == "__shell__":
            last_text = command[1]
            last = subprocess.run(command[1], cwd=str(cwd), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        else:
            last_text = " ".join(command)
            last = subprocess.run(command, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        if last.returncode != 0:
            return last, last_text
    return last, last_text


def _apply_patch_to_sandbox(patch_block: dict[str, Any], sandbox_root: Path, changed: dict[str, tuple[str, str]]) -> str:
    files = patch_block.get("files")
    if files:
        for item in files:
            path = Path(item.get("file_path", ""))
            if not path.is_absolute():
                path = sandbox_root / path
            if is_sensitive_target(path):
                return "Sandbox patch target is sensitive."
            old_text = item.get("old_text", path.read_text(encoding="utf-8") if path.exists() else "")
            new_text = item.get("new_text", "")
            path.parent.mkdir(parents=True, exist_ok=True)
            original = path.read_text(encoding="utf-8") if path.exists() else ""
            path.write_text(new_text, encoding="utf-8")
            changed[str(path)] = (original if str(path) not in changed else changed[str(path)][0], new_text)
        return ""
    path = Path(patch_block.get("file_path", ""))
    if not path.is_absolute():
        path = sandbox_root / path
    if is_sensitive_target(path) or not path.exists():
        return "Sandbox patch target is unavailable or sensitive."
    start = int(patch_block.get("start_line") or 0)
    end = int(patch_block.get("end_line") or start)
    if start < 1 or end < start:
        return "Sandbox patch line range is invalid."
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    if end > len(lines):
        return "Sandbox patch line range is outside the file."
    lines[start - 1:end] = str(patch_block.get("replacement") or "").splitlines(keepends=True)
    new_text = "".join(lines)
    path.write_text(new_text, encoding="utf-8")
    changed[str(path)] = (original if str(path) not in changed else changed[str(path)][0], new_text)
    return ""


def _final_patch_block(seed_block: dict[str, Any], root: Path, sandbox_root: Path, changed: dict[str, tuple[str, str]], commands: list[list[str]]) -> dict[str, Any]:
    files = []
    for sandbox_path, (old_text, new_text) in changed.items():
        rel = Path(sandbox_path).resolve().relative_to(sandbox_root.resolve())
        real_path = root / rel
        files.append({"file_path": str(real_path), "old_text": old_text, "new_text": new_text, "reason": "iterative validated patch"})
    validation_commands = [command for command in commands if command and command[0] != "__shell__"]
    if not validation_commands:
        validation_commands = [["python", "-m", "py_compile"]]
    return {
        "available": True,
        "action": "framework_multi_file",
        "reason": "Iterative validation converged.",
        "file_path": files[0]["file_path"] if files else seed_block.get("file_path", ""),
        "files": files,
        "patch": _combined_diff(files),
        "validation": "iterative sandbox validation",
        "validation_commands": validation_commands,
        "language": seed_block.get("language") or _infer_language(files),
        "framework": seed_block.get("framework") or _infer_framework(files),
        "requires_project_validation": True,
        "iterative": True,
    }


def _rebase_patch_block(block: dict[str, Any], old_root: Path, new_root: Path) -> dict[str, Any]:
    copied = json.loads(json.dumps(block))
    if copied.get("files"):
        for item in copied["files"]:
            item["file_path"] = str(_rebase_path(Path(item["file_path"]), old_root, new_root))
        copied["file_path"] = copied["files"][0]["file_path"]
        return copied
    if copied.get("file_path"):
        copied["file_path"] = str(_rebase_path(Path(copied["file_path"]), old_root, new_root))
    return copied


def _rebase_path(path: Path, old_root: Path, new_root: Path) -> Path:
    if not path.is_absolute():
        return new_root / path
    try:
        rel = path.resolve().relative_to(old_root.resolve())
        return new_root / rel
    except ValueError:
        return path


def _combined_diff(files: list[dict[str, str]]) -> str:
    import difflib

    chunks = []
    for item in files:
        old_lines = _preview_lines(item.get("old_text", ""))
        new_lines = _preview_lines(item.get("new_text", ""))
        chunks.append("".join(difflib.unified_diff(old_lines, new_lines, fromfile=item["file_path"], tofile=item["file_path"], lineterm="\n")))
    return "\n".join(chunk for chunk in chunks if chunk)


def _preview_lines(text: str) -> list[str]:
    return [line if line.endswith("\n") else f"{line}\n" for line in text.splitlines(keepends=True)]


def _failure_key(diagnostic: dict[str, Any]) -> str:
    return "|".join(str(diagnostic.get(key, "")).lower() for key in ("error_type", "root_cause", "file", "line", "message"))


def _is_regression(original: dict[str, Any], new: dict[str, Any]) -> bool:
    original_file = original.get("file") or ""
    new_file = new.get("file") or ""
    if new.get("root_cause") in {"port_already_in_use", "next_missing_env_var", "js_missing_env_var"}:
        return True
    return bool(original_file and new_file and Path(original_file).name != Path(new_file).name and not new.get("patch_block", {}).get("available"))


def _telemetry_from_failure(
    attempt: int,
    error_type: str,
    root_cause: str,
    confidence: int,
    command_text: str,
    validation_passed: bool,
    *,
    duplicate_failure: bool = False,
    regression_detected: bool = False,
    stopped_reason: str = "",
) -> RetryTelemetry:
    return RetryTelemetry(attempt, error_type, root_cause, confidence, command_text, validation_passed, duplicate_failure, regression_detected, stopped_reason)


def _has_sensitive_targets(block: dict[str, Any]) -> bool:
    files = block.get("files") or []
    if files:
        return any(is_sensitive_target(item.get("file_path", "")) for item in files)
    return is_sensitive_target(block.get("file_path", ""))


def _rollback_metadata_complete(block: dict[str, Any]) -> bool:
    files = block.get("files") or []
    return bool(files and all(item.get("file_path") for item in files))


def _snapshot_payload(snapshot) -> dict[str, Any]:
    return {
        "root": snapshot.root,
        "frameworks": snapshot.frameworks,
        "config_files": snapshot.config_files,
        "source_files": snapshot.source_files,
        "imports": snapshot.graph.imports,
        "exports": snapshot.graph.exports,
        "routes": snapshot.graph.routes,
        "components": snapshot.graph.components,
        "entrypoints": snapshot.graph.entrypoints,
    }


def _copy_project(root: Path, sandbox_root: Path) -> None:
    ignore = shutil.ignore_patterns(".git", ".ghostfix", ".next", "node_modules", "dist", "build", "coverage", "__pycache__", ".pytest_cache", ".venv", "venv")
    shutil.copytree(root, sandbox_root, ignore=ignore)


def _package_json(root: Path) -> dict[str, Any]:
    path = root / "package.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _python_target_from_command(command: str) -> str:
    parts = (command or "").split()
    for item in parts:
        if item.endswith(".py"):
            return item
    return ""


def _infer_language(files: list[dict[str, str]]) -> str:
    if files and Path(files[0].get("file_path", "")).suffix == ".py":
        return "python"
    return "javascript/typescript"


def _infer_framework(files: list[dict[str, str]]) -> str:
    if files and Path(files[0].get("file_path", "")).suffix == ".py":
        return "python"
    return "typescript"
