from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
import re


PROJECT_MARKERS = {
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "manage.py",
    "package.json",
    "tsconfig.json",
    "Dockerfile",
    "docker-compose.yml",
}
CONFIG_GLOBS = ("vite.config.*", "next.config.*")
SAFE_ROOT_FILES = PROJECT_MARKERS | {"app.py", "main.py"}
DEPENDENCY_FILES = {
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "package.json",
    "tsconfig.json",
    "Dockerfile",
    "docker-compose.yml",
}
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".ghostfix",
    ".ml",
    "node_modules",
    "dist",
    "build",
    "models",
}
SECRET_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "secrets.json",
    "secret.json",
    "id_rsa",
    "id_ed25519",
}
SECRET_NAME_RE = re.compile(r"(secret|password|token|api[_-]?key|private[_-]?key|credential|\.sqlite3?$|\.db$|\.pem$|\.key$)", re.IGNORECASE)
MAX_FILE_BYTES = 64 * 1024
DEFAULT_MAX_FILES = 12
DEFAULT_MAX_TOTAL_CHARS = 40_000


@dataclass
class ProjectContext:
    root: str
    files: dict[str, str] = field(default_factory=dict)
    frameworks: list[str] = field(default_factory=list)
    django_settings: list[str] = field(default_factory=list)
    language: str = "unknown"
    framework: str = "unknown"
    dependency_files: list[str] = field(default_factory=list)
    related_files: list[str] = field(default_factory=list)
    truncated: bool = False
    total_chars: int = 0

    def summary(self) -> str:
        parts = []
        if self.language:
            parts.append(f"language={self.language}")
        if self.framework and self.framework != "unknown":
            parts.append(f"framework={self.framework}")
        if self.frameworks:
            parts.append(f"frameworks={', '.join(self.frameworks)}")
        if self.dependency_files:
            parts.append(f"dependency_files={', '.join(self.dependency_files)}")
        if self.related_files:
            parts.append(f"related_files={', '.join(self.related_files)}")
        if self.files:
            parts.append(f"safe_files={', '.join(sorted(self.files))}")
        if self.django_settings:
            parts.append(f"django_settings={', '.join(self.django_settings)}")
        return "; ".join(parts)


def scan_project_context(
    cwd: str | None,
    command: str = "",
    start_path: str | None = None,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS,
) -> ProjectContext:
    root = detect_project_root(start_path or cwd or ".", cwd=cwd)
    context = ProjectContext(root=str(root))
    if not root.exists() or not root.is_dir():
        return context

    context.language = detect_language_for_path(start_path, command)

    for name in sorted(SAFE_ROOT_FILES):
        path = root / name
        _add_file(context, path, root, max_files=max_files, max_total_chars=max_total_chars)

    for pattern in CONFIG_GLOBS:
        for path in sorted(root.glob(pattern)):
            _add_file(context, path, root, max_files=max_files, max_total_chars=max_total_chars)

    include_django = _is_django_project(root, command, start_path)
    for settings_path in _find_django_settings(root, start_path) if include_django else []:
        if _add_file(context, settings_path, root, max_files=max_files, max_total_chars=max_total_chars):
            rel = settings_path.resolve().relative_to(root).as_posix()
            if rel not in context.django_settings:
                context.django_settings.append(rel)

    for related in collect_related_file_paths(root, start_path, include_framework_configs=include_django):
        _add_file(context, related, root, max_files=max_files, max_total_chars=max_total_chars, related=True)

    context.dependency_files = sorted(
        rel for rel in context.files if Path(rel).name in DEPENDENCY_FILES or _matches_config_glob(rel)
    )
    context.frameworks = _detect_frameworks(context.files, command)
    context.framework = context.frameworks[0] if context.frameworks else "unknown"
    return context


def detect_project_root(start_path: str | Path, cwd: str | Path | None = None) -> Path:
    cwd_path = Path(cwd or ".").resolve()
    candidate = Path(start_path)
    if not candidate.is_absolute():
        candidate = cwd_path / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = cwd_path
    start_dir = resolved.parent if resolved.suffix else resolved
    for directory in [start_dir, *start_dir.parents]:
        if any((directory / marker).exists() for marker in PROJECT_MARKERS):
            return directory
        if _has_config_marker(directory):
            return directory
        if directory == cwd_path.parent:
            break
    return cwd_path


def detect_language_for_path(path: str | None, command: str = "") -> str:
    text = f"{path or ''} {command}".lower()
    suffix = Path(path or "").suffix.lower()
    if suffix == ".py" or "python" in text or "manage.py" in text or "uvicorn" in text:
        return "python"
    if suffix in {".ts", ".tsx"} or "ts-node" in text or "tsx" in text or "tsc" in text:
        return "typescript"
    if suffix in {".js", ".jsx", ".mjs", ".cjs"} or "npm" in text or "pnpm" in text or "yarn" in text or "node" in text or "next" in text:
        return "javascript/node"
    return "unknown"


def collect_related_file_paths(root: Path, start_path: str | None, *, include_framework_configs: bool = False) -> list[Path]:
    paths: list[Path] = []
    start = _resolve_inside_root(root, start_path) if start_path else None
    if start and start.is_file():
        paths.append(start)
        paths.extend(_python_local_import_paths(root, start))
    if include_framework_configs:
        for name in ("settings.py", "urls.py", "asgi.py", "wsgi.py"):
            for path in root.rglob(name):
                if _is_safe_path(path, root):
                    paths.append(path)
                    break
    return _dedupe_paths(paths)


def _nearest_scan_root(cwd: str | None, command: str, start_path: str | None) -> Path:
    cwd_path = Path(cwd or ".").resolve()
    if start_path:
        candidate = Path(start_path)
        if not candidate.is_absolute():
            candidate = cwd_path / candidate
        start_dir = candidate.resolve().parent if candidate.suffix else candidate.resolve()
    else:
        start_dir = cwd_path

    command_lower = command.lower()
    if start_dir == cwd_path:
        return cwd_path

    for directory in [start_dir, *start_dir.parents]:
        if directory == cwd_path:
            break
        if cwd_path not in directory.parents and directory != cwd_path:
            continue
        if "manage.py" in command_lower and (directory / "manage.py").exists():
            return directory
        if any((directory / name).exists() for name in SAFE_ROOT_FILES):
            return directory
    return start_dir if start_dir.exists() else cwd_path


def _safe_read(path: Path, root: Path) -> str | None:
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if not _is_safe_path(resolved, root):
        return None
    try:
        if resolved.stat().st_size > MAX_FILE_BYTES:
            return None
        data = resolved.read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        return None
    return _redact_sensitive(data.decode("utf-8", errors="replace"))


def _is_safe_path(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if not resolved.is_file() or (root not in resolved.parents and resolved != root):
        return False
    if any(part in EXCLUDED_DIRS for part in resolved.parts):
        return False
    name = resolved.name.lower()
    if name in SECRET_FILE_NAMES or SECRET_NAME_RE.search(name):
        return False
    return True


def _add_file(
    context: ProjectContext,
    path: Path,
    root: Path,
    *,
    max_files: int,
    max_total_chars: int,
    related: bool = False,
) -> bool:
    if len(context.files) >= max_files:
        context.truncated = True
        return False
    content = _safe_read(path, root)
    if content is None:
        return False
    try:
        rel = path.resolve().relative_to(root).as_posix()
    except ValueError:
        return False
    remaining = max_total_chars - context.total_chars
    if remaining <= 0:
        context.truncated = True
        return False
    if len(content) > remaining:
        content = content[:remaining] + "\n# GhostFix context truncated"
        context.truncated = True
    context.files[rel] = content
    context.total_chars += len(content)
    if related and rel not in context.related_files:
        context.related_files.append(rel)
    return True


def _find_django_settings(root: Path, start_path: str | None = None) -> list[Path]:
    found = []
    if start_path and Path(start_path).name == "settings.py":
        path = Path(start_path)
        if not path.is_absolute():
            path = root / path
        if path.exists():
            found.append(path.resolve())
    direct = root / "settings.py"
    if direct.exists():
        found.append(direct)
    for child in root.iterdir() if root.exists() else []:
        if not child.is_dir() or child.name in EXCLUDED_DIRS:
            continue
        candidate = child / "settings.py"
        if candidate.exists():
            found.append(candidate)
    deduped = []
    seen = set()
    for path in found:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if any(part in EXCLUDED_DIRS for part in resolved.parts):
            continue
        deduped.append(resolved)
        if len(deduped) >= 3:
            break
    return deduped


def _is_django_project(root: Path, command: str, start_path: str | None) -> bool:
    lowered = f"{command} {start_path or ''}".lower()
    return "django" in lowered or "manage.py" in lowered or (root / "manage.py").exists()


def _detect_frameworks(files: dict[str, str], command: str) -> list[str]:
    haystack = "\n".join([command, *files.keys(), *files.values()]).lower()
    frameworks = []
    if "django" in haystack or "manage.py" in files:
        frameworks.append("django")
    if "fastapi" in haystack or "uvicorn" in haystack:
        frameworks.append("fastapi")
    if "flask" in haystack:
        frameworks.append("flask")
    if "uvicorn" in haystack and "uvicorn" not in frameworks:
        frameworks.append("uvicorn")
    if "vite" in haystack or any(Path(name).name.startswith("vite.config") for name in files):
        frameworks.append("vite")
    if "next" in haystack or any(Path(name).name.startswith("next.config") for name in files):
        frameworks.append("next.js")
    if "package.json" in files or "npm" in haystack or "node" in haystack:
        frameworks.append("node")
    return frameworks


def _python_local_import_paths(root: Path, start: Path) -> list[Path]:
    try:
        tree = ast.parse(start.read_text(encoding="utf-8"))
    except Exception:
        return []
    paths = []
    for node in ast.walk(tree):
        module = ""
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name.split(".", 1)[0]
                paths.extend(_module_candidates(root, start.parent, module))
        elif isinstance(node, ast.ImportFrom) and node.module:
            module = node.module.split(".", 1)[0]
            paths.extend(_module_candidates(root, start.parent, module))
    return _dedupe_paths(paths)


def _module_candidates(root: Path, base: Path, module: str) -> list[Path]:
    candidates = [
        base / f"{module}.py",
        base / module / "__init__.py",
        root / f"{module}.py",
        root / module / "__init__.py",
    ]
    return [path for path in candidates if _is_safe_path(path, root)]


def _resolve_inside_root(root: Path, path: str | None) -> Path | None:
    if not path:
        return None
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if root in resolved.parents or resolved == root:
        return resolved
    return None


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped = []
    seen = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


def _matches_config_glob(rel: str) -> bool:
    name = Path(rel).name
    return name.startswith("vite.config.") or name.startswith("next.config.")


def _has_config_marker(directory: Path) -> bool:
    return any(any(directory.glob(pattern)) for pattern in CONFIG_GLOBS)


def _redact_sensitive(text: str) -> str:
    redacted = []
    sensitive = re.compile(r"(secret|password|token|api[_-]?key|private[_-]?key)", re.IGNORECASE)
    for line in text.splitlines():
        if sensitive.search(line):
            redacted.append("# GhostFix redacted sensitive setting")
        else:
            redacted.append(line)
    return "\n".join(redacted)
