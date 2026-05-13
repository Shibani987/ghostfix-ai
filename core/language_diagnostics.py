from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any

from core.js_autofix import build_js_patch_plan, patch_block_from_plan
from core.php_autofix import build_php_patch_plan, patch_block_from_plan as php_patch_block_from_plan
from core.runtime_detector import infer_runtime_profile


def detect_language(command: str = "", output: str = "", file_path: str | None = None) -> str:
    text = f"{command}\n{output}\n{file_path or ''}".lower()
    suffix = Path(file_path or "").suffix.lower()
    if suffix == ".py" or re.search(r"\bpython\b|\bflask\b|\buvicorn\b|manage\.py|traceback \(most recent call last\):", text):
        return "python"
    if suffix in {".ts", ".tsx", ".mts", ".cts"} or re.search(r"\b(ts-node|tsx|tsc)\b|\.tsx?\b|typescript|type error:", text):
        return "typescript"
    if suffix in {".js", ".jsx", ".mjs", ".cjs"} or re.search(r"\b(node|npm|npx|pnpm|yarn|next|vite)\b|\.jsx?\b|node:|react|webpack", text):
        return "javascript/node"
    if suffix == ".php" or re.search(r"\bphp\b|artisan serve|php (fatal error|parse error|warning|notice)", text):
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
    profile = infer_runtime_profile(command=command, cwd=cwd, output=output)
    context = _framework_context(cwd, command)
    framework = profile.framework if profile.language in {"javascript/node", "typescript"} and profile.framework != "unknown" else _detect_js_framework(output, command, context, language)
    evidence = _context_evidence(output, command, context)
    if profile.dev_server_type != "unknown":
        evidence.append(f"runtime profile: {profile.dev_server_type}")
    route = _js_route(output)
    if route:
        evidence.append(f"route/API endpoint {route}")

    ollama_match = re.search(
        r"Could not connect to Ollama|OLLAMA_BASE_URL|ollama.{0,120}(?:ECONNREFUSED|fetch failed|failed to connect|connect)",
        output,
        re.IGNORECASE | re.DOTALL,
    )
    econnrefused_match = re.search(
        r"(?:connect\s+)?ECONNREFUSED\s+(?:(?:127\.0\.0\.1|localhost|\[?::1\]?)(?::\d+)?)?",
        output,
        re.IGNORECASE,
    )
    localhost_failed_match = re.search(
        r"(?:localhost|127\.0\.0\.1|::1).{0,120}(?:connection refused|failed to fetch|fetch failed|failed to connect|connect failed)",
        output,
        re.IGNORECASE | re.DOTALL,
    )
    http_500_match = re.search(
        r"\b(?:GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+(/\S+)\s+500\b|(?:status\s*[:=]\s*500|500\s+Internal Server Error)",
        output,
        re.IGNORECASE,
    )
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
    missing_export_match = re.search(
        r"(?:does not provide an export named|Attempted import error:)\s+['\"]?([A-Za-z_$][\w$]*)['\"]?",
        output,
        re.IGNORECASE,
    )
    missing_middleware_match = re.search(r"(?:body-parser|express\.json|req\.body).{0,120}(?:undefined|missing|not parsed)", output, re.IGNORECASE | re.DOTALL)
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
    vite_module_match = re.search(r"(?:Failed to resolve import|Does the file exist\?)\s*['\"]?([^'\"\n]+)?", output, re.IGNORECASE)

    if ollama_match:
        error_type = "OllamaConnectionError"
        message = _matching_line(output, ollama_match) or "Could not connect to Ollama."
        root_cause = "ollama_connection_failed"
        likely = "The Next.js/Node backend tried to call Ollama, but the Ollama service is not reachable at OLLAMA_BASE_URL."
        if route:
            likely += f" The failure surfaced while handling `{route}`."
        fix = "Start Ollama locally, verify OLLAMA_BASE_URL, and test the Ollama endpoint before rerunning the dev server."
        confidence = 95
    elif econnrefused_match or localhost_failed_match:
        match = econnrefused_match or localhost_failed_match
        target = _connection_target(output)
        error_type = "ConnectionRefusedError"
        message = _matching_line(output, match) or "A local backend connection was refused."
        root_cause = "localhost_connection_refused" if target else "backend_connection_refused"
        likely = "The server tried to call a local dependency, but nothing accepted the connection"
        likely += f" at `{target}`." if target else "."
        if route:
            likely += f" The failure surfaced while handling `{route}`."
        fix = "Start the dependent local service, verify the configured URL/port, and restart or retry the Next.js request."
        confidence = 92
    elif http_500_match:
        error_type = "Http500Error"
        route = route or (http_500_match.group(1) if http_500_match.lastindex else "")
        message = _matching_line(output, http_500_match) or "A Next.js route returned HTTP 500."
        root_cause = "next_backend_dependency_failure" if framework == "next.js" else "backend_dependency_failure"
        likely = "A server-side route/API handler returned HTTP 500, usually because a backend dependency or route exception failed."
        if route:
            likely += f" The failing endpoint appears to be `{route}`."
        fix = "Inspect the server-side exception above the 500 line, verify required services and environment variables, then retry the route."
        confidence = 86
    elif npm_package_json_missing:
        error_type = "NpmPackageJsonMissingError"
        message = "npm could not find package.json."
        root_cause = "npm_package_json_missing"
        likely = "npm was run outside a Node project or package.json is missing."
        fix = "cd into the project folder or create package.json with npm init."
        confidence = 94
    elif next_module_match or module_match or esm_match or vite_module_match:
        missing = (next_module_match or module_match or esm_match or vite_module_match).group(1) or "the requested module"
        error_type = "Cannot find module" if module_match else "ERR_MODULE_NOT_FOUND"
        if next_module_match:
            error_type = "ModuleNotFoundError"
        if vite_module_match:
            error_type = "ViteModuleResolutionError"
        message = f"Cannot find module '{missing}'"
        root_cause = "next_module_not_found" if framework == "next.js" else ("vite_module_not_found" if framework.startswith("vite") else "js_module_not_found")
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
    elif missing_export_match:
        symbol = missing_export_match.group(1)
        error_type = "MissingExportError"
        message = _matching_line(output, missing_export_match) or f"Missing export {symbol}."
        root_cause = "missing_named_export"
        likely = f"The import references `{symbol}`, but the target module does not expose that named export."
        fix = "Check the source module exports and the import statement. If this is a typo, rename the import/export to the exact existing symbol."
        confidence = 84
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
    elif missing_middleware_match:
        error_type = "ExpressMiddlewareError"
        message = _matching_line(output, missing_middleware_match) or "Express request middleware may be missing."
        root_cause = "express_missing_middleware"
        likely = "An Express route appears to read request data before the required parsing middleware is configured."
        fix = "Add the appropriate middleware near app setup, for example express.json() for JSON request bodies, then rerun the server."
        confidence = 78
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
        likely = f"{_framework_name(framework)} could not bind its configured port because another process is already listening there."
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
    diagnostic = _schema(
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
        route=route,
        runtime=profile.runtime,
        dev_server_type=profile.dev_server_type,
    )
    _attach_js_patch_metadata(diagnostic, cwd)
    return diagnostic


def _diagnose_php(output: str, command: str, cwd: str | None) -> dict[str, Any]:
    error_type = "UnknownError"
    message = _last_nonempty_line(output)
    root_cause = "php_runtime_error"
    likely = "PHP failed at runtime. Inspect the error text and reported file/line."
    fix = "Review the reported PHP file and fix the failing statement."
    confidence = 55
    profile = infer_runtime_profile(command=command, cwd=cwd, output=output)

    kind_match = re.search(r"PHP (Fatal error|Parse error|Warning|Notice):\s*(.+?)(?: in | on line |\n|$)", output, re.DOTALL)
    artisan_env_match = re.search(r"(?:No application encryption key has been specified|APP_KEY|\.env)", output, re.IGNORECASE)
    port_match = re.search(r"(?:address already in use|EADDRINUSE|Failed to listen).{0,120}(?::(\d+))?", output, re.IGNORECASE | re.DOTALL)
    detail = kind_match.group(2).strip() if kind_match else output

    if artisan_env_match:
        error_type = "LaravelEnvironmentError"
        message = _matching_line(output, artisan_env_match) or "Laravel environment/app key is missing."
        root_cause = "laravel_env_or_app_key_missing"
        likely = "Laravel cannot start because required local environment configuration such as APP_KEY or .env is missing."
        fix = "Create local Laravel environment configuration manually and run the appropriate Laravel key generation command yourself; GhostFix will not edit .env."
        confidence = 88
    elif port_match:
        error_type = "PortInUse"
        message = f"Port {port_match.group(1)} is already in use." if port_match.group(1) else "A PHP/Laravel server port is already in use."
        root_cause = "port_already_in_use"
        likely = "The PHP/Laravel dev server could not bind its configured port because another process is already listening there."
        fix = "Stop the process using that port or start the PHP/Laravel server on a different port."
        confidence = 86
    elif kind_match:
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
    diagnostic = _schema(
        language="php",
        error_type=error_type,
        message=message,
        file=file_path,
        line=line,
        framework=profile.framework if profile.framework != "unknown" else "php",
        root_cause=root_cause,
        likely_root_cause=likely,
        suggested_fix=fix,
        confidence=confidence,
        runtime=profile.runtime,
        dev_server_type=profile.dev_server_type,
    )
    _attach_php_patch_metadata(diagnostic, cwd)
    return diagnostic


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
    route: str = "",
    runtime: str = "unknown",
    dev_server_type: str = "unknown",
) -> dict[str, Any]:
    return {
        "language": language,
        "error_type": error_type,
        "message": message,
        "file": file,
        "line": line,
        "framework": framework,
        "runtime": runtime,
        "dev_server_type": dev_server_type,
        "root_cause": root_cause,
        "likely_root_cause": likely_root_cause,
        "suggested_fix": suggested_fix,
        "evidence": evidence or [],
        "route": route,
        "confidence": confidence,
        "source": "language_rule",
        "auto_fix_available": False,
        "safe_to_autofix": False,
        "patch_preview": "",
        "patch_block": {},
        "safety_reason": "Auto-fix is disabled for non-Python languages.",
        "why_auto_fix_blocked": "No allowlisted deterministic patch is available for this non-Python error.",
    }


def _attach_php_patch_metadata(diagnostic: dict[str, Any], cwd: str | None) -> None:
    if diagnostic.get("language") != "php":
        return
    if diagnostic.get("root_cause") in {"laravel_env_or_app_key_missing", "port_already_in_use", "php_class_not_found", "php_failed_opening_required"}:
        diagnostic["why_auto_fix_blocked"] = "PHP/Laravel config, dependency, env, port, and autoload issues require manual review."
        return
    plan = build_php_patch_plan(diagnostic, cwd=cwd)
    if not plan.available:
        diagnostic["why_auto_fix_blocked"] = plan.reason
        return
    diagnostic["auto_fix_available"] = True
    diagnostic["safe_to_autofix"] = True
    diagnostic["patch_preview"] = plan.preview
    diagnostic["patch_block"] = php_patch_block_from_plan(plan)
    diagnostic["safety_reason"] = plan.validation
    diagnostic["why_auto_fix_blocked"] = ""


def _attach_js_patch_metadata(diagnostic: dict[str, Any], cwd: str | None) -> None:
    if diagnostic.get("language") not in {"javascript/node", "typescript"}:
        return
    if _js_auto_fix_forbidden(diagnostic):
        diagnostic["safety_reason"] = "Auto-fix is disabled for non-Python languages."
        diagnostic["why_auto_fix_blocked"] = _js_block_reason(diagnostic)
        return
    plan = build_js_patch_plan(diagnostic, cwd=cwd)
    if not plan.available:
        diagnostic["safety_reason"] = "Auto-fix is disabled for non-Python languages."
        diagnostic["why_auto_fix_blocked"] = plan.reason
        return
    diagnostic["auto_fix_available"] = True
    diagnostic["safe_to_autofix"] = True
    diagnostic["patch_preview"] = plan.preview
    diagnostic["patch_block"] = patch_block_from_plan(plan)
    diagnostic["safety_reason"] = plan.validation or "Allowlisted deterministic JS/TS patch preview."
    diagnostic["why_auto_fix_blocked"] = ""


def _js_auto_fix_forbidden(diagnostic: dict[str, Any]) -> bool:
    root = diagnostic.get("root_cause")
    return root in {
        "ollama_connection_failed",
        "localhost_connection_refused",
        "backend_connection_refused",
        "next_backend_dependency_failure",
        "backend_dependency_failure",
        "next_missing_env_var",
        "js_missing_env_var",
        "port_already_in_use",
        "express_missing_middleware",
        "react_hydration_mismatch",
        "react_invalid_hook_call",
        "react_invalid_render_value",
        "typescript_type_error",
        "js_type_error",
        "js_reference_error",
        "js_unhandled_promise_rejection",
        "npm_script_failed",
        "npm_package_json_missing",
    }


def _js_block_reason(diagnostic: dict[str, Any]) -> str:
    root = diagnostic.get("root_cause")
    reasons = {
        "ollama_connection_failed": "external service/config issue; GhostFix will not start services or edit .env files.",
        "localhost_connection_refused": "external service/config issue; GhostFix will not start services or change URLs automatically.",
        "backend_connection_refused": "external service/config issue; GhostFix will not modify backend integration code automatically.",
        "next_backend_dependency_failure": "server route/API dependency failure; manual review required.",
        "backend_dependency_failure": "backend dependency failure; manual review required.",
        "next_missing_env_var": "environment/config issue; GhostFix may suggest .env.example guidance but will not write secrets.",
        "js_missing_env_var": "environment/config issue; GhostFix will not create or modify secret-bearing .env files.",
        "port_already_in_use": "process/port conflict; GhostFix will not stop processes or change server ports automatically.",
        "express_missing_middleware": "framework setup change requires manual review.",
        "react_hydration_mismatch": "rendering behavior mismatch requires component-level review.",
        "react_invalid_hook_call": "React hook placement can change runtime behavior and requires manual review.",
        "react_invalid_render_value": "render output change requires manual review.",
        "typescript_type_error": "type contract fixes can change behavior and require manual review.",
        "js_type_error": "runtime value-shape fixes can change behavior and require manual review.",
        "js_reference_error": "undefined symbol fixes can change behavior and require manual review.",
    }
    return reasons.get(root, "No allowlisted deterministic JS/TS patch is available.")


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


def _js_route(output: str) -> str:
    method_route = re.search(
        r"\b(?:GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+(/\S+?)(?:\s+(?:\d{3}|in\b|failed\b)|\s*$)",
        output,
        re.IGNORECASE,
    )
    if method_route:
        return method_route.group(1)
    api_path = re.search(r"\b(?:app|pages|src[/\\]app|src[/\\]pages)[/\\](api[/\\][^\s:]+)", output)
    if api_path:
        route = "/" + api_path.group(1).replace("\\", "/")
        return re.sub(r"/route\.[cm]?[jt]sx?$", "", route)
    return ""


def _connection_target(output: str) -> str:
    match = re.search(r"\b(?:https?://)?(?:localhost|127\.0\.0\.1|\[?::1\]?):\d+\b", output, re.IGNORECASE)
    return match.group(0) if match else ""


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
    if "express" in deps_text or "express" in command_lower:
        context["frameworks"].append("express")
    if "vite" in deps_text or "vite" in command_lower or any(root.glob("vite.config.*")):
        context["frameworks"].append("vite")
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
    if "vite" in frameworks:
        return "vite/react" if "react" in frameworks or "react" in text else "vite"
    if "react" in frameworks or "hydration" in text or "react-dom" in text:
        return "react"
    if "typescript" in frameworks or language == "typescript":
        return "typescript"
    if "express" in frameworks or "express" in text:
        return "express"
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
    return {"next.js": "Next.js", "react": "React", "typescript": "TypeScript", "express": "Express", "node": "Node.js"}.get(framework, framework or "Node.js")


def _module_fix(missing: str, framework: str) -> str:
    if missing.startswith((".", "/", "@/", "~")):
        return f"Correct the import path `{missing}`, confirm the target file exists, and verify tsconfig/jsconfig path aliases if used."
    if framework == "next.js":
        return f"Add `{missing}` to package.json manually if it is a dependency, or correct the import if it should be a local file. GhostFix will not run npm install."
    return f"Install `{missing}` manually if it is a dependency, or correct the import/require path if it is local. GhostFix will not install packages."
