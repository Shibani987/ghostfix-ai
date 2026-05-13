from __future__ import annotations

import json
import os
import re
import shlex
import shutil
from pathlib import Path
from typing import Any


PACKAGE_JSON_TEMPLATE = '{\n  "scripts": {\n    "dev": "node server.js"\n  }\n}\n'


def diagnose_tooling(command: str, cwd: str | None = None, output: str = "") -> dict[str, Any] | None:
    root = Path(cwd or ".").resolve()
    tokens = _tokens(command)
    lowered = [token.lower().strip('"') for token in tokens]
    text = f"{command}\n{output}".lower()

    explicit_tool_output = bool(output and _missing_executable(lowered, text, path_lookup=False))
    missing_exec = _missing_executable(lowered, text, path_lookup=not explicit_tool_output)
    if explicit_tool_output and missing_exec:
        return _missing_executable_diagnostic(missing_exec, command, root, output)

    if _is_django_command(lowered) and not _command_path_exists(tokens, root, "manage.py"):
        return _schema(
            command=command,
            language="python",
            framework="django",
            runtime="django",
            error_type="DjangoManagePyMissingError",
            root_cause="wrong_project_root",
            likely_root_cause="`python manage.py runserver` was started outside a Django project root; `manage.py` is missing.",
            suggested_fix="cd into the Django project directory that contains manage.py, then rerun `python manage.py runserver`.",
            evidence=[f"cwd `{root}`", "missing manage.py"],
            why="project-root issue; GhostFix will not create a Django project automatically.",
        )

    package = _read_package(root)
    package_text = json.dumps(package).lower() if package else ""

    if _is_npm_like_command(lowered) and not (root / "package.json").exists():
        diagnostic = _schema(
            command=command,
            language="javascript/node",
            framework="node",
            runtime=lowered[0] if lowered else "node",
            error_type="PackageJsonMissingError",
            root_cause="package_json_missing",
            likely_root_cause="A package-manager command was started outside a Node project root; package.json is missing.",
            suggested_fix="cd into the project folder that contains package.json, or create one intentionally with `npm init`.",
            evidence=[f"cwd `{root}`", "missing package.json"],
            why="wrong working directory or missing Node project metadata.",
        )
        diagnostic.update(_create_file_patch(root / "package.json", PACKAGE_JSON_TEMPLATE, "Create minimal package.json"))
        return diagnostic

    if len(lowered) >= 2 and lowered[0] == "node":
        entry = _unquote(tokens[1])
        if entry and not (root / entry).exists():
            return _schema(
                command=command,
                language="javascript/node",
                framework="node",
                runtime="node",
                error_type="MissingEntryPointError",
                root_cause="node_entrypoint_missing",
                likely_root_cause=f"`node {entry}` cannot start because `{entry}` does not exist in the current directory.",
                suggested_fix=f"cd into the correct project root, create `{entry}`, or run the actual Node entrypoint for this project.",
                evidence=[f"cwd `{root}`", f"missing {entry}"],
                why="missing entrypoint; GhostFix will not invent application code.",
            )

    if _is_flask_command(lowered):
        app_name = os.environ.get("FLASK_APP", "")
        if not app_name and not any((root / name).exists() for name in ("app.py", "wsgi.py")):
            diagnostic = _schema(
                command=command,
                language="python",
                framework="flask",
                runtime="flask",
                error_type="FlaskAppDiscoveryError",
                root_cause="flask_app_not_discovered",
                likely_root_cause="Flask cannot discover an app because FLASK_APP is not set and no app.py or wsgi.py exists in the current directory.",
                suggested_fix="Set `FLASK_APP`, use `flask --app app run`, or cd into the Flask project root.",
                evidence=[f"cwd `{root}`", "missing app.py/wsgi.py", "FLASK_APP not set"],
                why="Flask app discovery requires project intent; GhostFix will not create app code automatically.",
            )
            return diagnostic

    if _is_uvicorn_command(lowered):
        target = _uvicorn_target(tokens)
        if target:
            module_name = target.split(":", 1)[0].replace(".", "/") + ".py"
            if not (root / module_name).exists():
                return _schema(
                    command=command,
                    language="python",
                    framework="fastapi",
                    runtime="uvicorn",
                    error_type="MissingEntryPointError",
                    root_cause="uvicorn_module_missing",
                    likely_root_cause=f"Uvicorn target `{target}` points at `{module_name}`, but that module does not exist from the current directory.",
                    suggested_fix="cd into the FastAPI project root or run uvicorn with the correct module:app target, for example `uvicorn main:app --reload`.",
                    evidence=[f"cwd `{root}`", f"missing {module_name}"],
                    why="missing FastAPI/Uvicorn entrypoint; manual project-root correction required.",
                )

    if _is_php_artisan(lowered) and not (root / "artisan").exists():
        return _schema(
            command=command,
            language="php",
            framework="laravel",
            runtime="php",
            error_type="MissingEntryPointError",
            root_cause="laravel_artisan_missing",
            likely_root_cause="`php artisan serve` was started outside a Laravel project root; the artisan entrypoint is missing.",
            suggested_fix="cd into the Laravel project directory that contains `artisan`, then rerun `php artisan serve`.",
            evidence=[f"cwd `{root}`", "missing artisan"],
            why="wrong project root; GhostFix will not create a Laravel project automatically.",
        )

    if "next" in f"{text}\n{package_text}" and (root / "package.json").exists() and not any(root.glob("next.config.*")) and not ((root / "app").is_dir() or (root / "pages").is_dir() or (root / "src" / "app").is_dir()):
        return _schema(
            command=command,
            language="javascript/node",
            framework="next.js",
            runtime="next",
            error_type="InvalidProjectRootError",
            root_cause="invalid_next_project_root",
            likely_root_cause="The command looks like a Next.js dev command, but this directory lacks next.config.*, app/, pages/, or src/app markers.",
            suggested_fix="cd into the actual Next.js app root or verify the project layout before running `next dev`.",
            evidence=[f"cwd `{root}`", "missing Next.js root markers"],
            why="project-root issue; GhostFix will not create framework configuration automatically.",
        )

    if re.search(r"\btsc\b|typescript", text) and not (root / "tsconfig.json").exists():
        return _schema(
            command=command,
            language="typescript",
            framework="typescript",
            runtime="tsc",
            error_type="InvalidProjectRootError",
            root_cause="tsconfig_missing",
            likely_root_cause="TypeScript tooling was started in a directory without tsconfig.json.",
            suggested_fix="cd into the TypeScript project root or create tsconfig.json intentionally with your project settings.",
            evidence=[f"cwd `{root}`", "missing tsconfig.json"],
            why="TypeScript project configuration requires developer intent.",
        )

    if missing_exec:
        return _missing_executable_diagnostic(missing_exec, command, root, output)

    return None


def _schema(
    *,
    command: str,
    language: str,
    framework: str,
    runtime: str,
    error_type: str,
    root_cause: str,
    likely_root_cause: str,
    suggested_fix: str,
    evidence: list[str],
    why: str,
) -> dict[str, Any]:
    return {
        "language": language,
        "framework": framework,
        "runtime": runtime,
        "dev_server_type": "tooling/preflight",
        "error_type": error_type,
        "message": likely_root_cause,
        "file": "",
        "line": 0,
        "root_cause": root_cause,
        "likely_root_cause": likely_root_cause,
        "suggested_fix": suggested_fix,
        "evidence": [f"command `{command}`", *evidence],
        "route": "",
        "confidence": 94,
        "source": "tooling_preflight",
        "auto_fix_available": False,
        "safe_to_autofix": False,
        "patch_preview": "",
        "patch_block": {},
        "safety_reason": why,
        "why_auto_fix_blocked": why,
    }


def _create_file_patch(path: Path, content: str, reason: str) -> dict[str, Any]:
    if path.name in {".env", ".env.local", ".env.production"}:
        return {}
    if path.exists():
        return {}
    preview = f"--- {path}\n+++ {path}\n@@\n" + "".join(f"+{line}" for line in content.splitlines(keepends=True))
    return {
        "auto_fix_available": True,
        "safe_to_autofix": True,
        "patch_preview": preview,
        "patch_block": {
            "available": True,
            "reason": reason,
            "action": "create_file",
            "file_path": str(path),
            "replacement": content,
            "patch": preview,
            "language": "setup",
        },
        "safety_reason": "Allowlisted project setup file creation; confirmation required.",
        "why_auto_fix_blocked": "",
    }


def _missing_executable(lowered: list[str], text: str, *, path_lookup: bool = True) -> str:
    executable = lowered[0] if lowered else ""
    aliases = {
        "pnpm": "pnpm",
        "npm": "npm",
        "node": "node",
        "php": "php",
        "python": "python",
        "python3": "python",
        "uvicorn": "uvicorn",
        "flask": "flask",
    }
    if path_lookup and executable in aliases and shutil.which(executable) is None:
        return aliases[executable]
    patterns = {
        "pnpm": ("pnpm is not recognized", "pnpm: command not found", "'pnpm' is not recognized"),
        "npm": ("npm is not recognized", "npm: command not found", "'npm' is not recognized"),
        "node": ("node is not recognized", "node: command not found", "'node' is not recognized"),
        "php": ("php is not recognized", "php: command not found", "'php' is not recognized"),
        "python": ("python is not recognized", "python: command not found", "'python' is not recognized"),
        "uvicorn": ("uvicorn is not recognized", "uvicorn: command not found", "no module named uvicorn", "'uvicorn' is not recognized"),
        "flask": ("flask is not recognized", "flask: command not found", "no module named flask", "'flask' is not recognized"),
    }
    for name, needles in patterns.items():
        if any(needle in text for needle in needles):
            return name
    return ""


def _missing_executable_diagnostic(name: str, command: str, root: Path, output: str) -> dict[str, Any]:
    mapping = {
        "pnpm": ("PnpmNotInstalledError", "javascript/node", "node", "pnpm", "Install pnpm with `npm install -g pnpm`, or use this project's supported package manager."),
        "npm": ("NpmNotInstalledError", "javascript/node", "node", "npm", "Install Node.js/npm, then reopen the terminal so npm is on PATH."),
        "node": ("NodeRuntimeMissingError", "javascript/node", "node", "node", "Install Node.js, then reopen the terminal so node is on PATH."),
        "php": ("PhpRuntimeMissingError", "php", "php", "php", "Install PHP and ensure `php` is on PATH before running PHP/Laravel commands."),
        "python": ("PythonRuntimeMissingError", "python", "python", "python", "Install Python or activate the environment that provides python on PATH."),
        "uvicorn": ("UvicornNotInstalledError", "python", "fastapi", "uvicorn", "Install uvicorn in the active virtualenv with `pip install uvicorn`, or run the server from the environment where it is installed."),
        "flask": ("FlaskAppDiscoveryError", "python", "flask", "flask", "Install Flask in the active virtualenv with `pip install flask`, then run `flask --app app run` if app discovery needs help."),
    }
    error_type, language, framework, runtime, fix = mapping[name]
    return _schema(
        command=command,
        language=language,
        framework=framework,
        runtime=runtime,
        error_type=error_type,
        root_cause="missing_executable_in_path",
        likely_root_cause=f"`{name}` is not installed or is not available on PATH for this terminal.",
        suggested_fix=fix,
        evidence=[f"cwd `{root}`", output.strip()[:240] if output else f"`{name}` not found by PATH lookup"],
        why="tool/runtime installation issue; GhostFix will not install packages automatically.",
    )


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command or "", posix=False)
    except ValueError:
        return (command or "").split()


def _unquote(value: str) -> str:
    return value.strip("\"'")


def _command_path_exists(tokens: list[str], root: Path, filename: str) -> bool:
    for token in tokens:
        value = _unquote(token)
        if Path(value).name != filename:
            continue
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        if path.exists():
            return True
    return (root / filename).exists()


def _read_package(root: Path) -> dict:
    path = root / "package.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _is_npm_like_command(lowered: list[str]) -> bool:
    return bool(lowered) and lowered[0] in {"npm", "pnpm", "yarn"} and any(token in lowered for token in {"run", "start", "dev", "build"})


def _is_django_command(lowered: list[str]) -> bool:
    return any("manage.py" in token for token in lowered) and "runserver" in lowered


def _is_flask_command(lowered: list[str]) -> bool:
    return bool(lowered) and lowered[0] == "flask"


def _is_uvicorn_command(lowered: list[str]) -> bool:
    return bool(lowered) and lowered[0] == "uvicorn"


def _is_php_artisan(lowered: list[str]) -> bool:
    return len(lowered) >= 3 and lowered[0] == "php" and lowered[1] == "artisan" and lowered[2] == "serve"


def _uvicorn_target(tokens: list[str]) -> str:
    for token in tokens[1:]:
        value = _unquote(token)
        if value.startswith("-"):
            continue
        if ":" in value:
            return value
    return ""
