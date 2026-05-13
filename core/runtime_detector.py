from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

@dataclass
class RuntimeProfile:
    command: str
    language: str = "unknown"
    framework: str = "unknown"
    runtime: str = "unknown"
    project_root: str = ""
    dev_server_type: str = "unknown"
    evidence: list[str] | None = None
    missing_markers: list[str] | None = None

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "language": self.language,
            "framework": self.framework,
            "runtime": self.runtime,
            "project_root": self.project_root,
            "dev_server_type": self.dev_server_type,
            "evidence": self.evidence or [],
            "missing_markers": self.missing_markers or [],
        }


def classify_runtime(command: str = "", output: str = "", file_path: str | None = None) -> str:
    """Classify runtime logs into GhostFix watch-mode language buckets."""
    from core.language_diagnostics import detect_language

    return detect_language(command=command, output=output, file_path=file_path)


def infer_runtime_profile(command: str = "", cwd: str | None = None, output: str = "", file_path: str | None = None) -> RuntimeProfile:
    root = _project_root(cwd)
    evidence: list[str] = []
    missing: list[str] = []
    command_lower = (command or "").lower()
    tokens = _tokens(command)
    package = _package_json(root)
    deps = _package_deps(package)
    scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
    script_command = _npm_script_command(tokens, scripts)
    script_lower = script_command.lower()
    text = "\n".join([command_lower, script_lower, output.lower(), " ".join(deps)])

    from core.language_diagnostics import detect_language

    language = detect_language(command=command, output=output, file_path=file_path)
    framework = "unknown"
    runtime = "unknown"
    dev_server_type = "unknown"

    if "manage.py" in command_lower:
        language, framework, runtime, dev_server_type = "python", "django", "django", "django dev server"
    elif command_lower.startswith("flask ") or " flask run" in f" {command_lower}":
        language, framework, runtime, dev_server_type = "python", "flask", "flask", "flask dev server"
    elif "uvicorn" in command_lower:
        language, framework, runtime, dev_server_type = "python", "fastapi", "uvicorn", "asgi dev server"
    elif re.search(r"\bpython\b.*\b(app|main|run)\.py\b", command_lower):
        language, framework, runtime, dev_server_type = "python", _python_script_framework(root), "python", "python script"
    elif "php artisan serve" in command_lower:
        language, framework, runtime, dev_server_type = "php", "laravel", "php", "laravel dev server"
    elif re.search(r"\bphp\b.*\.php\b", command_lower):
        language, framework, runtime, dev_server_type = "php", "php", "php", "php script"
    elif "next" in text:
        language, framework, runtime, dev_server_type = "javascript/node", "next.js", "next", "next dev server"
    elif "vite" in text:
        language, framework, runtime, dev_server_type = "javascript/node", "vite/react" if "react" in text else "vite", "vite", "vite dev server"
    elif "tsc" in text or "typescript" in text:
        language, framework, runtime, dev_server_type = "typescript", "typescript", "tsc", "typescript build"
    elif "express" in text or re.search(r"\bnode\b", command_lower):
        language, framework, runtime, dev_server_type = "javascript/node", "express" if "express" in text else "node", "node", "node dev server"
    elif language == "php":
        framework, runtime, dev_server_type = "php", "php", "php runtime"

    if package:
        evidence.append("package.json detected")
    elif any(token in command_lower for token in ("npm", "pnpm", "yarn", "next", "vite", "tsc")):
        missing.append("package.json")
    if script_command:
        evidence.append(f"package script resolves to `{script_command}`")
    if (root / "manage.py").exists():
        evidence.append("manage.py detected")
    elif "manage.py" in command_lower:
        missing.append("manage.py")
    if any(root.glob("next.config.*")):
        evidence.append("next.config detected")
    elif "next" in text:
        missing.append("next.config.*")
    if any(root.glob("vite.config.*")):
        evidence.append("vite.config detected")
    elif "vite" in text:
        missing.append("vite.config.*")
    if "tsc" in text and not (root / "tsconfig.json").exists():
        missing.append("tsconfig.json")

    return RuntimeProfile(
        command=command,
        language=language,
        framework=framework,
        runtime=runtime,
        project_root=str(root),
        dev_server_type=dev_server_type,
        evidence=evidence,
        missing_markers=missing,
    )


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command or "", posix=False)
    except ValueError:
        return (command or "").split()


def _project_root(cwd: str | None) -> Path:
    root = Path(cwd or ".").resolve()
    for directory in [root, *root.parents]:
        if any((directory / marker).exists() for marker in ("package.json", "pyproject.toml", "manage.py", "requirements.txt", "composer.json")):
            return directory
    return root


def _package_json(root: Path) -> dict:
    path = root / "package.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _package_deps(package: dict) -> list[str]:
    deps: list[str] = []
    for key in ("dependencies", "devDependencies"):
        value = package.get(key)
        if isinstance(value, dict):
            deps.extend(value)
    return deps


def _npm_script_command(tokens: list[str], scripts: dict) -> str:
    if not isinstance(scripts, dict) or len(tokens) < 2:
        return ""
    lowered = [token.lower().strip('"') for token in tokens]
    script = ""
    if lowered[:2] in (["npm", "start"], ["pnpm", "start"], ["yarn", "start"]):
        script = "start"
    elif len(lowered) >= 3 and lowered[0] in {"npm", "pnpm", "yarn"} and lowered[1] == "run":
        script = lowered[2]
    elif len(lowered) >= 2 and lowered[0] in {"pnpm", "yarn"}:
        script = lowered[1]
    value = scripts.get(script)
    return value if isinstance(value, str) else ""


def _python_script_framework(root: Path) -> str:
    for name in ("app.py", "main.py", "run.py"):
        path = root / name
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except Exception:
            continue
        if "fastapi" in text:
            return "fastapi"
        if "flask" in text:
            return "flask"
        if "django" in text:
            return "django"
    return "python"
