from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def detect_language(command: str = "", output: str = "", file_path: str | None = None) -> str:
    text = f"{command}\n{output}\n{file_path or ''}".lower()
    suffix = Path(file_path or "").suffix.lower()
    if suffix == ".py" or re.search(r"\bpython\b|traceback \(most recent call last\):", text):
        return "python"
    if suffix in {".ts", ".tsx", ".mts", ".cts"} or re.search(r"\b(ts-node|tsx|tsc)\b|\.tsx?\b", text):
        return "typescript"
    if suffix in {".js", ".mjs", ".cjs"} or re.search(r"\b(node|npm|npx)\b|\.js\b|node:", text):
        return "javascript/node"
    if suffix == ".php" or re.search(r"\bphp\b|php (fatal error|parse error|warning|notice)", text):
        return "php"
    return "unknown"


def diagnose_non_python(output: str, command: str = "", cwd: str | None = None) -> dict[str, Any] | None:
    language = detect_language(command=command, output=output)
    if language in {"javascript/node", "typescript"}:
        return _diagnose_javascript(output, command, cwd, language=language)
    if language == "php":
        return _diagnose_php(output, command, cwd)
    return None


def _diagnose_javascript(output: str, command: str, cwd: str | None, language: str = "javascript/node") -> dict[str, Any]:
    error_type = "UnknownError"
    message = _last_nonempty_line(output)
    root_cause = "node_runtime_error"
    likely = "Node.js failed at runtime. Inspect the stack trace and failing line before changing code."
    fix = "Review the stack trace and fix the failing JavaScript or TypeScript statement/import."
    confidence = 55

    module_match = re.search(r"Cannot find module ['\"]([^'\"]+)['\"]", output)
    esm_match = re.search(r"ERR_MODULE_NOT_FOUND.*?Cannot find (?:package|module) ['\"]([^'\"]+)['\"]", output, re.DOTALL)
    promise_match = re.search(r"UnhandledPromiseRejection(?:Warning)?:?\s*(.*)", output)
    typed_match = re.search(r"\b(ReferenceError|TypeError|SyntaxError):\s*(.+)", output)
    npm_match = re.search(r"npm ERR!\s+(.+)", output)
    npm_package_json_missing = re.search(r"npm ERR!.*(?:ENOENT|could not read package\.json|package\.json).*", output, re.IGNORECASE | re.DOTALL)
    port_match = re.search(r"\b(EADDRINUSE|address already in use|listen EADDRINUSE)\b.*?(?::(\d+))?", output, re.IGNORECASE | re.DOTALL)

    if npm_package_json_missing:
        error_type = "NpmPackageJsonMissingError"
        message = "npm could not find package.json."
        root_cause = "npm_package_json_missing"
        likely = "npm was run outside a Node project or package.json is missing."
        fix = "cd into the project folder or create package.json with npm init."
        confidence = 94
    elif module_match or esm_match:
        missing = (module_match or esm_match).group(1)
        error_type = "Cannot find module" if module_match else "ERR_MODULE_NOT_FOUND"
        message = f"Cannot find module '{missing}'"
        root_cause = "js_module_not_found"
        likely = f"Node.js could not resolve the module `{missing}` from the current import/require path."
        fix = f"Install `{missing}` if it is a package, or correct the require/import path if it is a local module."
        confidence = 90
    elif promise_match:
        error_type = "UnhandledPromiseRejection"
        message = promise_match.group(1).strip() or "Unhandled promise rejection"
        root_cause = "js_unhandled_promise_rejection"
        likely = "A Promise rejected without a catch handler or surrounding try/await error handling."
        fix = "Add await/try/catch or a .catch() handler and handle the rejected error path explicitly."
        confidence = 84
    elif typed_match:
        error_type = typed_match.group(1)
        message = typed_match.group(2)
        if error_type == "ReferenceError":
            root_cause = "js_reference_error"
            likely = "JavaScript referenced a variable or symbol that is not defined in scope."
            fix = "Define the variable before use, import it, or correct the spelling."
            confidence = 88
        elif error_type == "TypeError":
            root_cause = "js_type_error"
            likely = "JavaScript attempted an operation on a value with an incompatible type or shape."
            fix = "Check the value before using it and guard null/undefined or incorrect object shapes."
            confidence = 82
        elif error_type == "SyntaxError":
            root_cause = "js_syntax_error"
            likely = "Node.js could not parse the JavaScript file because the syntax is invalid."
            fix = "Fix the syntax at the reported line before rerunning Node."
            confidence = 86
    elif port_match:
        error_type = "EADDRINUSE"
        port = port_match.group(2) or ""
        message = f"Port {port} is already in use." if port else "A dev server port is already in use."
        root_cause = "port_already_in_use"
        likely = "The dev server could not bind its configured port because another process is already listening there."
        fix = "Stop the process using that port or start the dev server on a different port."
        confidence = 90
    elif npm_match:
        error_type = "npm_error"
        message = npm_match.group(1).strip()
        root_cause = "npm_script_failed"
        likely = "The npm dev script exited with an error. The first stack trace or npm ERR line is the best fix target."
        fix = "Inspect the npm ERR details above, fix the failing script/import/configuration, then rerun npm."
        confidence = 72

    file_path, line = _js_location(output)
    return _schema(
        language=language,
        error_type=error_type,
        message=message,
        file=file_path,
        line=line,
        framework="typescript" if language == "typescript" else "node",
        root_cause=root_cause,
        likely_root_cause=likely,
        suggested_fix=fix,
        confidence=confidence,
    )


def _diagnose_php(output: str, command: str, cwd: str | None) -> dict[str, Any]:
    error_type = "UnknownError"
    message = _last_nonempty_line(output)
    root_cause = "php_runtime_error"
    likely = "PHP failed at runtime. Inspect the error text and reported file/line."
    fix = "Review the reported PHP file and fix the failing statement."
    confidence = 55

    kind_match = re.search(r"PHP (Fatal error|Parse error|Warning|Notice):\s*(.+?)(?: in | on line |\n|$)", output, re.DOTALL)
    detail = kind_match.group(2).strip() if kind_match else output

    if kind_match:
        kind = kind_match.group(1)
        message = detail
        if kind == "Parse error":
            error_type = "PHP Parse error"
            root_cause = "php_parse_error"
            likely = "PHP could not parse the file because the syntax is invalid."
            fix = "Fix the syntax at the reported line, then rerun PHP."
            confidence = 88
        elif "Undefined variable" in detail:
            error_type = "PHP Warning"
            root_cause = "php_undefined_variable"
            likely = "PHP code reads a variable before it has been assigned a value."
            fix = "Initialize the variable before use or check that the expected input exists."
            confidence = 86
        elif "Class" in detail and "not found" in detail:
            error_type = "PHP Fatal error"
            root_cause = "php_class_not_found"
            likely = "PHP could not load the referenced class."
            fix = "Check the class name, namespace, autoloader, and required dependency."
            confidence = 86
        elif "Call to undefined function" in detail:
            error_type = "PHP Fatal error"
            root_cause = "php_undefined_function"
            likely = "PHP called a function that is not defined or not loaded."
            fix = "Define the function, include the correct file, or enable the required extension."
            confidence = 86
        elif "Failed opening required" in detail:
            error_type = "PHP Fatal error"
            root_cause = "php_failed_opening_required"
            likely = "PHP could not open a required file."
            fix = "Correct the require/include path or ensure the required file exists."
            confidence = 86
        else:
            error_type = f"PHP {kind}"
            root_cause = f"php_{kind.lower().replace(' ', '_')}"
            confidence = 78

    file_path, line = _php_location(output)
    return _schema(
        language="php",
        error_type=error_type,
        message=message,
        file=file_path,
        line=line,
        framework="php",
        root_cause=root_cause,
        likely_root_cause=likely,
        suggested_fix=fix,
        confidence=confidence,
    )


def _schema(
    *,
    language: str,
    error_type: str,
    message: str,
    file: str,
    line: int,
    framework: str,
    root_cause: str,
    likely_root_cause: str,
    suggested_fix: str,
    confidence: int,
) -> dict[str, Any]:
    return {
        "language": language,
        "error_type": error_type,
        "message": message,
        "file": file,
        "line": line,
        "framework": framework,
        "root_cause": root_cause,
        "likely_root_cause": likely_root_cause,
        "suggested_fix": suggested_fix,
        "confidence": confidence,
        "source": "language_rule",
        "auto_fix_available": False,
        "safety_reason": "Auto-fix is disabled for non-Python languages.",
    }


def _js_location(output: str) -> tuple[str, int]:
    match = re.search(r"\(([^()\n]+\.[cm]?[jt]sx?):(\d+):\d+\)", output) or re.search(r"\n\s+at\s+([^()\s]+\.[cm]?[jt]sx?):(\d+):\d+", output)
    if match:
        return match.group(1), int(match.group(2))
    direct = re.search(r"([^:\s]+\.[cm]?[jt]sx?):(\d+):\d+", output)
    return (direct.group(1), int(direct.group(2))) if direct else ("", 0)


def _php_location(output: str) -> tuple[str, int]:
    match = re.search(r" in (.+?\.php) on line (\d+)", output) or re.search(r" in (.+?\.php):(\d+)", output)
    return (match.group(1), int(match.group(2))) if match else ("", 0)


def _last_nonempty_line(text: str) -> str:
    for line in reversed((text or "").splitlines()):
        if line.strip():
            return line.strip()
    return ""
