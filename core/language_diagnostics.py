from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any


def detect_language(command: str = "", output: str = "", file_path: str | None = None) -> str:
    text = f"{command}\n{output}\n{file_path or ''}".lower()
    suffix = Path(file_path or "").suffix.lower()
    if suffix == ".py" or re.search(r"\bpython\b|traceback \(most recent call last\):", text):
        return "python"
    if suffix in {".ts", ".tsx", ".mts", ".cts"} or re.search(r"\b(ts-node|tsx|tsc)\b|\.tsx?\b|typescript|type error:", text):
        return "typescript"
    if suffix in {".js", ".jsx", ".mjs", ".cjs"} or re.search(r"\b(node|npm|npx|pnpm|yarn|next)\b|\.jsx?\b|node:|react|webpack", text):
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
    context = _framework_context(cwd, command)
    framework = _detect_js_framework(output, command, context, language)
    evidence = _context_evidence(output, command, context)

    module_match = re.search(r"Cannot find module ['\"]([^'\"]+)['\"]", output)
    esm_match = re.search(r"ERR_MODULE_NOT_FOUND.*?Cannot find (?:package|module) ['\"]([^'\"]+)['\"]", output, re.DOTALL)
    next_module_match = re.search(r"Module not found:\s*(?:Can't resolve|Can(?:not|'t) resolve)\s+['\"]([^'\"]+)['\"]", output, re.IGNORECASE)
    next_import_trace = re.search(r"Import trace for requested module:\s*([\s\S]{0,500})", output, re.IGNORECASE)
    env_match = re.search(
        r"(?:Missing|required|not set|undefined).{0,80}(?:environment variable|env var|process\.env\.)(?:\s+|['\"`])([A-Z][A-Z0-9_]+)",
        output,
        re.IGNORECASE,
    )
    next_env_match = re.search(r"process\.env\.([A-Z][A-Z0-9_]+)", output)
    ts_match = re.search(r"(?:Type error:|TS\d{4}:)\s*(.+)", output)
    hydration_match = re.search(r"Hydration (?:failed|error)|server rendered HTML didn't match the client|Text content does not match server-rendered HTML", output, re.IGNORECASE)
    invalid_hook_match = re.search(r"Invalid hook call|Hooks can only be called inside", output, re.IGNORECASE)
    react_element_match = re.search(r"Element type is invalid|Objects are not valid as a React child", output, re.IGNORECASE)
    syntax_build_match = re.search(
        r"(?:Failed to compile|SyntaxError:|Parsing ecmascript source code failed|Unexpected token|Unexpected end of input|Expected .+? got .+)",
        output,
        re.IGNORECASE,
    )
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
    elif next_module_match or module_match or esm_match:
        missing = (next_module_match or module_match or esm_match).group(1)
        error_type = "Cannot find module" if module_match else "ERR_MODULE_NOT_FOUND"
        if next_module_match:
            error_type = "ModuleNotFoundError"
        message = f"Cannot find module '{missing}'"
        root_cause = "next_module_not_found" if framework == "next.js" else "js_module_not_found"
        trace = _first_trace_line(next_import_trace.group(1)) if next_import_trace else ""
        likely = f"{_framework_name(framework)} could not resolve `{missing}` from an import or require path."
        if trace:
            likely += f" Import trace points at `{trace}`."
            evidence.append(f"import trace includes {trace}")
        fix = _module_fix(missing, framework)
        confidence = 92 if framework == "next.js" else 90
    elif env_match or next_env_match:
        env_name = (env_match or next_env_match).group(1)
        error_type = "MissingEnvironmentVariable"
        message = f"Missing environment variable {env_name}."
        root_cause = "next_missing_env_var" if framework == "next.js" else "js_missing_env_var"
        likely = f"The app expects `{env_name}` at runtime/build time, but it is not available in the current environment."
        fix = (
            f"Define `{env_name}` in the shell or the appropriate local env file, then restart the dev server. "
            "Do not commit secret values."
        )
        confidence = 90
    elif hydration_match:
        error_type = "ReactHydrationError"
        message = _matching_line(output, hydration_match) or "Hydration failed."
        root_cause = "react_hydration_mismatch"
        likely = "React rendered different markup on the server and client, often from browser-only state, time/random values, or client-only APIs during server render."
        fix = "Move browser-only logic into useEffect/client components, make initial render deterministic, and check conditional markup around the reported component."
        confidence = 88
    elif ts_match:
        error_type = "TypeScriptError"
        message = ts_match.group(1).strip()
        root_cause = "typescript_type_error"
        likely = "The TypeScript compiler found a type contract mismatch during the dev/build step."
        fix = "Update the value, prop, return type, or interface so the assigned type matches the expected type; avoid bypassing with any unless intentional."
        confidence = 87
    elif invalid_hook_match:
        error_type = "ReactHookError"
        message = _matching_line(output, invalid_hook_match) or "Invalid hook call."
        root_cause = "react_invalid_hook_call"
        likely = "A React hook is being called outside a function component/custom hook, inside a conditional path, or with duplicate React versions."
        fix = "Call hooks only at the top level of function components/custom hooks and check for duplicate React packages."
        confidence = 87
    elif react_element_match:
        error_type = "ReactRenderError"
        message = _matching_line(output, react_element_match) or "React render error."
        root_cause = "react_invalid_render_value"
        likely = "React received an invalid component/value while rendering."
        fix = "Check imports/exports for the component and ensure rendered children are strings, numbers, elements, arrays, or null."
        confidence = 84
    elif syntax_build_match:
        error_type = "BuildSyntaxError"
        if typed_match and typed_match.group(1) == "SyntaxError":
            error_type = "SyntaxError"
            message = typed_match.group(2)
        else:
            message = _matching_line(output, syntax_build_match) or message
        root_cause = "next_build_syntax_error" if framework == "next.js" else "js_build_syntax_error"
        likely = f"{_framework_name(framework)} could not compile the source because a JavaScript/TypeScript syntax or build parse error was reported."
        fix = "Open the reported file and line, fix the parse error, then rerun the dev/build command."
        confidence = 84
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
    if file_path:
        evidence.append(f"reported location {file_path}:{line or '?'}")
    return _schema(
        language=language,
        error_type=error_type,
        message=message,
        file=file_path,
        line=line,
        framework=framework,
        root_cause=root_cause,
        likely_root_cause=likely,
        suggested_fix=fix,
        confidence=confidence,
        evidence=evidence,
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
    evidence: list[str] | None = None,
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
        "evidence": evidence or [],
        "confidence": confidence,
        "source": "language_rule",
        "auto_fix_available": False,
        "safe_to_autofix": False,
        "safety_reason": "Auto-fix is disabled for non-Python languages.",
    }


def _js_location(output: str) -> tuple[str, int]:
    match = (
        re.search(r"\(([^()\n]+\.[cm]?[jt]sx?):(\d+):\d+\)", output)
        or re.search(r"\n\s+at\s+([^()\s]+\.[cm]?[jt]sx?):(\d+):\d+", output)
        or re.search(r"\n\s*(?:\.\/)?([^:\n]+\.[cm]?[jt]sx?):(\d+):\d+", output)
    )
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


def _framework_context(cwd: str | None, command: str) -> dict[str, Any]:
    root = Path(cwd or ".")
    context: dict[str, Any] = {
        "has_package_json": False,
        "package_scripts": [],
        "dependencies": [],
        "has_next_config": False,
        "has_tsconfig": False,
        "has_app_dir": False,
        "has_pages_dir": False,
        "has_src_dir": False,
        "frameworks": [],
    }
    package_path = root / "package.json"
    if package_path.exists() and package_path.is_file():
        context["has_package_json"] = True
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except Exception:
            package = {}
        scripts = package.get("scripts") if isinstance(package, dict) else {}
        deps: dict[str, Any] = {}
        if isinstance(package, dict):
            for key in ("dependencies", "devDependencies"):
                value = package.get(key)
                if isinstance(value, dict):
                    deps.update(value)
        context["package_scripts"] = sorted(scripts) if isinstance(scripts, dict) else []
        context["dependencies"] = sorted(deps)
    context["has_next_config"] = any(root.glob("next.config.*"))
    context["has_tsconfig"] = (root / "tsconfig.json").exists()
    context["has_app_dir"] = (root / "app").is_dir() or (root / "src" / "app").is_dir()
    context["has_pages_dir"] = (root / "pages").is_dir() or (root / "src" / "pages").is_dir()
    context["has_src_dir"] = (root / "src").is_dir()

    deps_text = " ".join(context["dependencies"]).lower()
    command_lower = command.lower()
    if "next" in deps_text or "next" in command_lower or context["has_next_config"] or context["has_app_dir"]:
        context["frameworks"].append("next.js")
    if "react" in deps_text or "react" in command_lower:
        context["frameworks"].append("react")
    if context["has_tsconfig"] or "typescript" in deps_text or "tsc" in command_lower:
        context["frameworks"].append("typescript")
    if context["has_package_json"] or any(token in command_lower for token in ("npm", "pnpm", "yarn", "node")):
        context["frameworks"].append("node")
    return context


def _detect_js_framework(output: str, command: str, context: dict[str, Any], language: str) -> str:
    text = f"{command}\n{output}".lower()
    frameworks = context.get("frameworks") or []
    if "next.js" in frameworks or "next dev" in text or "next build" in text or ".next/" in text or "next/dist" in text:
        return "next.js"
    if "react" in frameworks or "hydration" in text or "react-dom" in text:
        return "react"
    if "typescript" in frameworks or language == "typescript":
        return "typescript"
    return "node"


def _context_evidence(output: str, command: str, context: dict[str, Any]) -> list[str]:
    evidence = [f"command `{command}`"] if command else []
    frameworks = context.get("frameworks") or []
    if frameworks:
        evidence.append(f"project signals: {', '.join(frameworks)}")
    markers = []
    for label, key in (
        ("package.json", "has_package_json"),
        ("next.config", "has_next_config"),
        ("tsconfig.json", "has_tsconfig"),
        ("app directory", "has_app_dir"),
        ("pages directory", "has_pages_dir"),
        ("src directory", "has_src_dir"),
    ):
        if context.get(key):
            markers.append(label)
    if markers:
        evidence.append(f"framework context markers: {', '.join(markers)}")
    first_error = _first_error_line(output)
    if first_error:
        evidence.append(f"log line: {first_error}")
    return evidence


def _first_error_line(output: str) -> str:
    for line in (output or "").splitlines():
        stripped = line.strip()
        if any(token in stripped.lower() for token in ("error", "failed", "cannot find", "can't resolve", "hydration", "type error", "syntaxerror")):
            return stripped[:220]
    return ""


def _matching_line(output: str, match: re.Match[str]) -> str:
    start = match.start()
    line_start = output.rfind("\n", 0, start) + 1
    line_end = output.find("\n", start)
    if line_end == -1:
        line_end = len(output)
    return output[line_start:line_end].strip()


def _first_trace_line(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _framework_name(framework: str) -> str:
    return {"next.js": "Next.js", "react": "React", "typescript": "TypeScript", "node": "Node.js"}.get(framework, framework or "Node.js")


def _module_fix(missing: str, framework: str) -> str:
    if missing.startswith((".", "/", "@/", "~")):
        return f"Correct the import path `{missing}`, confirm the target file exists, and verify tsconfig/jsconfig path aliases if used."
    if framework == "next.js":
        return f"Add `{missing}` to package.json manually if it is a dependency, or correct the import if it should be a local file. GhostFix will not run npm install."
    return f"Install `{missing}` manually if it is a dependency, or correct the import/require path if it is local. GhostFix will not install packages."
