from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path


JS_TS_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
SENSITIVE_PARTS = {"auth", "login", "oauth", "session", "payment", "billing", "database", "db", "security", "secret"}


@dataclass
class JsPatchPlan:
    available: bool
    reason: str
    file_path: str = ""
    start_line: int = 0
    end_line: int = 0
    replacement: str = ""
    preview: str = ""
    validation: str = ""


def build_js_patch_plan(diagnostic: dict, cwd: str | None = None) -> JsPatchPlan:
    """Build a narrow deterministic JS/TS patch preview.

    This intentionally covers only low-risk text repairs. Dependency installs,
    env files, framework config, auth, database, payment, and business logic stay
    suggestion-only.
    """

    file_path = _resolve_file(diagnostic.get("file") or "", cwd)
    if not file_path:
        return JsPatchPlan(False, "No exact local JS/TS target file was found.")
    if file_path.suffix.lower() not in JS_TS_SUFFIXES:
        return JsPatchPlan(False, "Target is not a JavaScript or TypeScript source file.")
    if _is_sensitive_path(file_path):
        return JsPatchPlan(False, "Auto-fix is blocked for auth, database, payment, security, or secret-sensitive paths.")

    try:
        lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        return JsPatchPlan(False, f"Could not read target file: {exc}")

    if diagnostic.get("root_cause") in {"js_build_syntax_error", "next_build_syntax_error", "js_syntax_error"}:
        plan = _missing_semicolon_plan(file_path, lines, int(diagnostic.get("line") or 0))
        if plan.available:
            return plan

    if diagnostic.get("root_cause") in {"js_module_not_found", "next_module_not_found"}:
        plan = _relative_import_extension_plan(file_path, lines, diagnostic, cwd)
        if plan.available:
            return plan

    if diagnostic.get("root_cause") in {"missing_named_export", "missing_default_export"}:
        plan = _export_mismatch_plan(file_path, lines, diagnostic, cwd)
        if plan.available:
            return plan

    return JsPatchPlan(False, "No allowlisted deterministic JS/TS patch matched this error.")


def patch_block_from_plan(plan: JsPatchPlan) -> dict:
    return {
        "available": plan.available,
        "reason": plan.reason,
        "file_path": plan.file_path,
        "start_line": plan.start_line,
        "end_line": plan.end_line,
        "replacement": plan.replacement,
        "patch": plan.preview,
        "validation": plan.validation,
        "language": "javascript/typescript",
    }


def _missing_semicolon_plan(path: Path, lines: list[str], line_no: int) -> JsPatchPlan:
    if line_no < 1 or line_no > len(lines):
        return JsPatchPlan(False, "No exact syntax line was available for a semicolon repair.")
    line = lines[line_no - 1]
    stripped = line.rstrip("\r\n")
    ending = _line_ending(line)
    if not stripped.strip():
        return JsPatchPlan(False, "Blank lines are not safe semicolon targets.")
    if stripped.rstrip().endswith((";", "{", "}", ":", ",", "(", "[", "`")):
        return JsPatchPlan(False, "Line does not look like a missing-semicolon repair.")
    if re.search(r"\b(if|for|while|switch|function|class|try|catch|else)\b", stripped.strip()):
        return JsPatchPlan(False, "Control-flow syntax is not a safe semicolon target.")
    replacement = stripped.rstrip() + ";" + ending
    return _single_line_plan(path, lines, line_no, replacement, "Safe missing-semicolon patch preview can be applied.")


def _relative_import_extension_plan(path: Path, lines: list[str], diagnostic: dict, cwd: str | None) -> JsPatchPlan:
    missing = _missing_module_name(diagnostic)
    if not missing.startswith("."):
        return JsPatchPlan(False, "Package dependencies are suggestion-only; GhostFix will not install packages.")
    root = Path(cwd or path.parent)
    base = (path.parent / missing).resolve()
    candidates = [base.with_suffix(suffix) for suffix in JS_TS_SUFFIXES]
    candidates += [base / f"index{suffix}" for suffix in JS_TS_SUFFIXES]
    exact = [candidate for candidate in candidates if candidate.exists() and candidate.is_file()]
    if len(exact) != 1:
        return JsPatchPlan(False, "Relative import repair requires exactly one matching local target file.")
    target = exact[0]
    suffix = target.suffix
    replacement_module = missing + suffix if target.name != f"index{suffix}" else missing.rstrip("/") + f"/index{suffix}"
    for index, line in enumerate(lines, start=1):
        if missing not in line or not re.search(r"\b(import|require)\b", line):
            continue
        replacement = line.replace(missing, replacement_module, 1)
        if replacement == line:
            continue
        return _single_line_plan(
            path,
            lines,
            index,
            replacement,
            f"Safe relative import extension patch preview found target {target.relative_to(root) if _is_relative_to(target, root) else target}.",
        )
    return JsPatchPlan(False, "Could not find the exact import line to patch.")


def _export_mismatch_plan(path: Path, lines: list[str], diagnostic: dict, cwd: str | None) -> JsPatchPlan:
    symbol = _missing_export_name(diagnostic)
    if not symbol:
        return JsPatchPlan(False, "Missing export repair requires an exact symbol name.")
    for index, line in enumerate(lines, start=1):
        if symbol not in line or " from " not in line:
            continue
        module = _module_from_import_line(line)
        if not module or not module.startswith("."):
            continue
        target = _resolve_js_module(path.parent, module)
        if not target:
            continue
        try:
            target_text = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "export default" in target_text and re.search(rf"import\s*\{{\s*{re.escape(symbol)}\s*\}}\s*from", line):
            replacement = re.sub(rf"import\s*\{{\s*{re.escape(symbol)}\s*\}}\s*from", f"import {symbol} from", line, count=1)
            return _single_line_plan(
                path,
                lines,
                index,
                replacement,
                f"Safe export mismatch patch: `{target.name}` has a default export and the import used a named export.",
            )
        exported = _named_exports(target_text)
        exact_case = [name for name in exported if name.lower() == symbol.lower() and name != symbol]
        if len(exact_case) == 1:
            replacement = line.replace(symbol, exact_case[0], 1)
            return _single_line_plan(
                path,
                lines,
                index,
                replacement,
                f"Safe export mismatch patch: exact local export `{exact_case[0]}` differs only by spelling/case.",
            )
    return JsPatchPlan(False, "Export mismatch repair requires exactly one local target module with a compatible export.")


def _single_line_plan(path: Path, lines: list[str], line_no: int, replacement: str, reason: str) -> JsPatchPlan:
    old_lines = lines[:]
    new_lines = lines[:]
    new_lines[line_no - 1:line_no] = replacement.splitlines(keepends=True)
    return JsPatchPlan(
        available=True,
        reason=reason,
        file_path=str(path),
        start_line=line_no,
        end_line=line_no,
        replacement=replacement,
        preview=_diff_preview(path, old_lines, new_lines),
        validation="single-line deterministic JS/TS patch preview",
    )


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


def _missing_module_name(diagnostic: dict) -> str:
    message = str(diagnostic.get("message") or "")
    match = re.search(r"Cannot find module ['\"]([^'\"]+)['\"]", message)
    if match:
        return match.group(1)
    for item in diagnostic.get("evidence") or []:
        match = re.search(r"['\"]([^'\"]+)['\"]", str(item))
        if match:
            return match.group(1)
    return ""


def _missing_export_name(diagnostic: dict) -> str:
    message = str(diagnostic.get("message") or "")
    match = re.search(r"(?:export named|Attempted import error:)\s+['\"]?([A-Za-z_$][\w$]*)['\"]?", message)
    if match:
        return match.group(1)
    match = re.search(r"['\"]([A-Za-z_$][\w$]*)['\"]\s+is not exported", message)
    return match.group(1) if match else ""


def _module_from_import_line(line: str) -> str:
    match = re.search(r"from\s+['\"]([^'\"]+)['\"]", line)
    return match.group(1) if match else ""


def _resolve_js_module(base: Path, module: str) -> Path | None:
    direct = base / module
    candidates = [direct.with_suffix(suffix) for suffix in JS_TS_SUFFIXES]
    candidates += [direct / f"index{suffix}" for suffix in JS_TS_SUFFIXES]
    exact = [candidate.resolve() for candidate in candidates if candidate.exists() and candidate.is_file()]
    return exact[0] if len(exact) == 1 else None


def _named_exports(text: str) -> list[str]:
    exports = re.findall(r"export\s+(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)", text)
    for group in re.findall(r"export\s*\{([^}]+)\}", text):
        exports.extend(part.strip().split(" as ")[-1] for part in group.split(","))
    return sorted({item for item in exports if item})


def _is_sensitive_path(path: Path) -> bool:
    lowered = [part.lower() for part in path.parts]
    short = {"db"}
    return any(
        part in SENSITIVE_PARTS
        or any(token not in short and token in part for token in SENSITIVE_PARTS)
        for part in lowered
    )


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return ""


def _diff_preview(path: Path, old_lines: list[str], new_lines: list[str]) -> str:
    return "".join(
        difflib.unified_diff(
            _ensure_preview_newlines(old_lines),
            _ensure_preview_newlines(new_lines),
            fromfile=str(path),
            tofile=str(path),
            lineterm="\n",
        )
    )


def _ensure_preview_newlines(lines: list[str]) -> list[str]:
    return [line if line.endswith("\n") else f"{line}\n" for line in lines]


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
