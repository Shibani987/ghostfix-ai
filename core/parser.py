import re


ERROR_LINE_RE = re.compile(
    r"^(?P<type>[A-Za-z_][A-Za-z0-9_.]*[A-Za-z_][A-Za-z0-9_]*)(?:: (?P<message>.*))?$"
)
FRAME_RE = re.compile(r'File "(.+?)", line (\d+)(?:, in (.+))?')
NODE_ERROR_RE = re.compile(r"\b(?:ReferenceError|TypeError|SyntaxError|Error|RangeError|URIError): .+")
MAX_RUNTIME_PARSE_CHARS = 256_000


def traceback_frames(stderr: str) -> list[dict]:
    frames = []
    lines = (stderr or "").splitlines()
    for index, line in enumerate(lines):
        match = FRAME_RE.search(line)
        if not match:
            continue
        code = ""
        for candidate in lines[index + 1:index + 4]:
            stripped = candidate.strip()
            if not stripped or stripped.startswith(("^", "~")):
                continue
            if _is_exception_line(stripped):
                break
            code = stripped
            break
        frames.append({
            "file": match.group(1),
            "line": int(match.group(2)),
            "function": match.group(3) or "",
            "code": code,
        })
    return frames


def parse_error(stderr: str):
    try:
        if not stderr:
            return None

        frames = traceback_frames(stderr)
        error_matches = [_exception_match(line.strip()) for line in stderr.splitlines()]
        error_matches = [match for match in error_matches if match]
        package_match = re.search(r"No module named '(.+?)'", stderr)

        if error_matches:
            error_match = error_matches[-1]
            qualified_type = error_match.group("type")
            error_type = qualified_type.rsplit(".", 1)[-1]
            message = error_match.group("message") or qualified_type
        else:
            qualified_type = "UnknownError"
            error_type = "UnknownError"
            message = stderr.strip().split("\n")[-1]

        frame = _best_user_frame(frames) if frames else {}

        return {
            "raw": stderr,
            "file": frame.get("file"),
            "line": frame.get("line"),
            "type": error_type,
            "qualified_type": qualified_type,
            "message": message,
            "missing_package": package_match.group(1) if package_match else None,
            "frames": frames,
        }
    except Exception:
        return {
            "raw": str(stderr or ""),
            "file": None,
            "line": None,
            "type": "UnknownError",
            "qualified_type": "UnknownError",
            "message": "GhostFix could not parse this malformed error log.",
            "missing_package": None,
            "frames": [],
        }


def extract_runtime_error(output: str, command: str = "") -> dict | None:
    """Extract a structured error block from noisy live server output."""
    try:
        return _extract_runtime_error_guarded(output, command=command)
    except Exception:
        return None


def _extract_runtime_error_guarded(output: str, command: str = "") -> dict | None:
    if not output:
        return None
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    if not isinstance(output, str):
        return None

    text = output[-MAX_RUNTIME_PARSE_CHARS:].replace("\r\n", "\n")
    command_missing = _extract_command_not_found(text)
    if command_missing:
        return {
            "raw": command_missing,
            "type": "CommandNotFoundError",
            "qualified_type": "CommandNotFoundError",
            "message": command_missing,
            "language": _language_from_text(text, command),
            "framework": _framework_from_text(text, command),
            "error_block": command_missing,
            "kind": "command_not_found",
        }

    package_json_missing = _extract_npm_package_json_missing(text)
    if package_json_missing:
        return {
            "raw": package_json_missing,
            "type": "NpmPackageJsonMissingError",
            "qualified_type": "NpmPackageJsonMissingError",
            "message": "npm could not find package.json.",
            "language": _language_from_text(text, command),
            "framework": "node",
            "error_block": package_json_missing,
            "kind": "npm_package_json_missing",
        }

    python_block = _extract_python_traceback(text)
    if python_block:
        parsed = parse_error(python_block) or {}
        parsed.update({
            "language": "python",
            "framework": _framework_from_text(text, command),
            "error_block": python_block,
            "kind": "python_traceback",
        })
        return parsed

    port = re.search(r"\b(EADDRINUSE|address already in use|listen EADDRINUSE|That port is already in use)\b.*?(?::(\d+))?", text, re.IGNORECASE | re.DOTALL)
    if port:
        return {
            "raw": port.group(0).strip(),
            "type": "PortInUse",
            "qualified_type": "PortInUse",
            "message": f"Port {port.group(2)} is already in use." if port.group(2) else "A server port is already in use.",
            "language": _language_from_text(text, command),
            "framework": _framework_from_text(text, command),
            "error_block": port.group(0).strip(),
            "kind": "port_in_use",
        }

    next_block = _extract_next_error(text)
    if next_block:
        error_type = _next_error_type(next_block)
        return {
            "raw": next_block,
            "type": error_type,
            "qualified_type": error_type,
            "message": _next_error_message(next_block),
            "language": _language_from_text(text, command),
            "framework": _framework_from_text(text, command),
            "error_block": next_block,
            "kind": "next_error",
        }

    node_block = _extract_node_error(text)
    if node_block:
        first = NODE_ERROR_RE.search(node_block)
        error_type = first.group(0).split(":", 1)[0] if first else "NodeError"
        message = first.group(0).split(":", 1)[1].strip() if first and ":" in first.group(0) else node_block.splitlines()[0].strip()
        return {
            "raw": node_block,
            "type": error_type,
            "qualified_type": error_type,
            "message": message,
            "language": _language_from_text(text, command),
            "framework": "node",
            "error_block": node_block,
            "kind": "node_stack",
        }

    npm_lines = [line for line in text.splitlines() if line.startswith("npm ERR!")]
    if npm_lines:
        block = "\n".join(npm_lines)
        return {
            "raw": block,
            "type": "npm_error",
            "qualified_type": "npm_error",
            "message": npm_lines[0].replace("npm ERR!", "", 1).strip(),
            "language": _language_from_text(text, command),
            "framework": "node",
            "error_block": block,
            "kind": "npm_error",
        }

    env_match = re.search(r"(?:missing|required|not set).{0,40}(?:environment variable|env var)\s+['\"]?([A-Z][A-Z0-9_]+)['\"]?", text, re.IGNORECASE)
    if env_match:
        return {
            "raw": env_match.group(0),
            "type": "MissingEnvironmentVariable",
            "qualified_type": "MissingEnvironmentVariable",
            "message": f"Missing environment variable {env_match.group(1)}.",
            "language": _language_from_text(text, command),
            "framework": _framework_from_text(text, command),
            "error_block": env_match.group(0),
            "kind": "missing_env_var",
        }

    return None


def _extract_python_traceback(text: str) -> str:
    start = text.find("Traceback (most recent call last):")
    if start == -1:
        return ""
    lines = text[start:].splitlines()
    collected = []
    last_exception_index = -1
    for index, line in enumerate(lines):
        stripped = line.strip()
        if last_exception_index >= 0 and _looks_like_log_boundary(stripped):
            break
        collected.append(line)
        if _is_exception_line(stripped):
            last_exception_index = index
    if last_exception_index >= 0:
        collected = collected[:last_exception_index + 1]
    return "\n".join(collected) + ("\n" if collected else "")


def _looks_like_log_boundary(line: str) -> bool:
    if not line:
        return False
    if line.startswith(("Traceback ", "File ", "~", "^", "During handling", "The above exception")):
        return False
    if line.startswith(("INFO", "DEBUG", "WARNING", "WARN", "ERROR", "Started ", "Watching ")):
        return True
    if NODE_ERROR_RE.search(line) or line.startswith(("npm ERR!", "webpack ")):
        return True
    return False


def _extract_node_error(text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if NODE_ERROR_RE.search(line) or "Cannot find module" in line:
            block = lines[index:index + 12]
            return "\n".join(block).strip()
    return ""


def _extract_next_error(text: str) -> str:
    patterns = (
        r"Module not found:\s*(?:Can't resolve|Cannot resolve)[\s\S]{0,1600}",
        r"Import trace for requested module:[\s\S]{0,1200}",
        r"(?:Failed to compile|Failed to build|Type error:|Parsing ecmascript source code failed|Hydration failed)[\s\S]{0,1600}",
        r"Error:\s*(?:Missing|required|not set|undefined).{0,100}process\.env\.[A-Z][A-Z0-9_]+[\s\S]{0,800}",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _trim_frontend_block(match.group(0))
    return ""


def _trim_frontend_block(block: str) -> str:
    lines = block.strip().splitlines()
    trimmed = []
    for line in lines:
        stripped = line.strip()
        if trimmed and stripped.startswith(("ready -", "event -", "wait -", "info  -", "Local:", "npm ERR!")):
            break
        trimmed.append(line)
        if len(trimmed) >= 24:
            break
    return "\n".join(trimmed).strip()


def _next_error_type(block: str) -> str:
    lowered = block.lower()
    if "module not found" in lowered or "can't resolve" in lowered or "cannot resolve" in lowered:
        return "ModuleNotFoundError"
    if "type error:" in lowered or re.search(r"\bTS\d{4}:", block):
        return "TypeScriptError"
    if "hydration failed" in lowered:
        return "ReactHydrationError"
    if "environment variable" in lowered or "process.env" in lowered:
        return "MissingEnvironmentVariable"
    if "syntaxerror" in lowered or "parsing ecmascript" in lowered or "failed to compile" in lowered:
        return "BuildSyntaxError"
    return "NextBuildError"


def _next_error_message(block: str) -> str:
    for line in block.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return "Next.js build/runtime error."


def _extract_command_not_found(text: str) -> str:
    lowered = text.lower()
    if "uvicorn" not in lowered:
        return ""
    patterns = (
        r"'uvicorn' is not recognized as an internal or external command[^\n]*",
        r"uvicorn: command not found[^\n]*",
        r"no module named uvicorn[^\n]*",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return ""


def _extract_npm_package_json_missing(text: str) -> str:
    lowered = text.lower()
    if "npm" not in lowered or "package.json" not in lowered:
        return ""
    if "enoent" not in lowered and "could not read package.json" not in lowered:
        return ""
    lines = [
        line
        for line in text.splitlines()
        if "npm ERR!" in line or "package.json" in line or "ENOENT" in line
    ]
    return "\n".join(lines).strip() or text.strip()


def _language_from_text(text: str, command: str) -> str:
    from core.language_diagnostics import detect_language

    return detect_language(command=command, output=text)


def _framework_from_text(text: str, command: str) -> str:
    combined = f"{command}\n{text}".lower()
    if "next dev" in combined or "next build" in combined or "next/dist" in combined or ".next/" in combined or "next.js" in combined:
        return "next.js"
    if "react" in combined or "hydration" in combined:
        return "react"
    if "manage.py" in combined or "django" in combined:
        return "django"
    if "uvicorn" in combined or "fastapi" in combined:
        return "fastapi"
    if "npm" in combined or "node" in combined:
        return "node"
    return "python" if "traceback (most recent call last):" in combined else "unknown"


def _best_user_frame(frames: list[dict]) -> dict:
    for frame in reversed(frames):
        lowered = str(frame.get("file") or "").lower()
        if not any(part in lowered for part in ("site-packages", "<frozen", "\\lib\\", "/lib/")):
            return frame
    return frames[-1]


def _exception_match(line: str):
    match = ERROR_LINE_RE.match(line)
    if not match:
        return None
    name = match.group("type").rsplit(".", 1)[-1]
    if _looks_like_exception_name(name):
        return match
    return None


def _is_exception_line(line: str) -> bool:
    return _exception_match(line) is not None


def _looks_like_exception_name(name: str) -> bool:
    return (
        name.endswith(("Error", "Exception", "Warning"))
        or name
        in {
            "TemplateNotFound",
            "TemplateDoesNotExist",
            "ImproperlyConfigured",
            "HTTPException",
            "OperationalError",
            "ProgrammingError",
            "ValidationError",
            "KeyboardInterrupt",
            "SystemExit",
        }
    )
