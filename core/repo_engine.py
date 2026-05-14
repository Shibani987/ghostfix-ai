from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SUPPORTED_SUFFIXES = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".php"}
JS_TS_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
CONFIG_NAMES = {"package.json", "tsconfig.json", "manage.py", "requirements.txt", "pyproject.toml"}
CONFIG_PATTERNS = ("next.config.*",)
IGNORED_PARTS = {
    ".git",
    ".ghostfix",
    "__pycache__",
    ".pytest_cache",
    ".next",
    "node_modules",
    "build",
    "dist",
    "coverage",
    "venv",
    ".venv",
    "env",
    "vendor",
}
SECRET_NAMES = {".env", ".env.local", ".env.production", ".env.development", "secrets.json", "secret.json"}
SENSITIVE_PARTS = {
    "auth",
    "login",
    "oauth",
    "session",
    "payment",
    "billing",
    "database",
    "db",
    "schema",
    "migration",
    "deploy",
    "infra",
    "security",
    "secret",
}
CLASSIFICATIONS = {
    "deterministic_safe",
    "deterministic_with_validation",
    "suggestion_only",
    "unsafe_blocked",
    "needs_user_confirmation",
    "multi_file_required",
}


@dataclass
class RepoFrame:
    file: str
    line: int = 0
    function: str = ""
    code: str = ""


@dataclass
class DependencyGraph:
    imports: dict[str, list[str]] = field(default_factory=dict)
    exports: dict[str, list[str]] = field(default_factory=dict)
    routes: dict[str, list[str]] = field(default_factory=dict)
    components: dict[str, list[str]] = field(default_factory=dict)
    entrypoints: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class RepoSnapshot:
    root: str
    frameworks: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    graph: DependencyGraph = field(default_factory=DependencyGraph)
    ignored_dirs: list[str] = field(default_factory=lambda: sorted(IGNORED_PARTS))

    def summary(self) -> str:
        parts = [
            f"root={self.root}",
            f"frameworks={', '.join(self.frameworks) or 'unknown'}",
            f"configs={', '.join(self.config_files) or 'none'}",
            f"sources={len(self.source_files)}",
        ]
        route_count = sum(len(values) for values in self.graph.routes.values())
        if route_count:
            parts.append(f"routes={route_count}")
        component_count = sum(len(values) for values in self.graph.components.values())
        if component_count:
            parts.append(f"components={component_count}")
        entrypoint_count = sum(len(values) for values in self.graph.entrypoints.values())
        if entrypoint_count:
            parts.append(f"entrypoints={entrypoint_count}")
        return "; ".join(parts)


@dataclass
class StructuredPatchPlan:
    classification: str
    file_targets: list[str]
    line_ranges: list[tuple[int, int]]
    explanation: str
    validation_strategy: list[str]
    rollback_metadata: dict[str, Any]
    patch_preview: str = ""
    confidence: int = 0
    apply_prompt: str = "APPLY_FIX? y/n"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["line_ranges"] = [list(item) for item in self.line_ranges]
        return payload


def build_repo_snapshot(cwd: str | Path | None, *, max_files: int = 240) -> RepoSnapshot:
    root = Path(cwd or ".").resolve()
    snapshot = RepoSnapshot(root=str(root))
    if not root.exists():
        return snapshot

    for path in _iter_project_files(root, max_files=max_files):
        rel = _rel(path, root)
        if path.name in CONFIG_NAMES or any(path.match(pattern) for pattern in CONFIG_PATTERNS):
            snapshot.config_files.append(rel)
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            snapshot.source_files.append(rel)
            _index_source_file(snapshot.graph, path, root)

    snapshot.config_files = sorted(set(snapshot.config_files))
    snapshot.source_files = sorted(set(snapshot.source_files))
    snapshot.frameworks = _detect_frameworks(root, snapshot)
    return snapshot


def select_business_frame(frames: Iterable[dict[str, Any]], root: str | Path) -> dict[str, Any] | None:
    root_path = Path(root).resolve()
    candidates = []
    for frame in frames or []:
        path = resolve_project_path(frame.get("file"), root_path)
        if not path or not is_business_source(path, root_path):
            continue
        candidates.append({**frame, "file": str(path)})
    return candidates[-1] if candidates else None


def resolve_project_path(value: str | None, root: str | Path) -> Path | None:
    if not value or str(value).startswith("<"):
        return None
    root_path = Path(root).resolve()
    path = Path(value)
    if not path.is_absolute():
        path = root_path / path
    try:
        resolved = path.resolve()
    except OSError:
        return None
    return resolved if resolved.exists() and _is_relative_to(resolved, root_path) else None


def is_business_source(path: str | Path, root: str | Path) -> bool:
    path = Path(path)
    root = Path(root).resolve()
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if not resolved.is_file() or not _is_relative_to(resolved, root):
        return False
    if resolved.suffix.lower() not in SUPPORTED_SUFFIXES:
        return False
    lowered = [part.lower() for part in resolved.parts]
    return not any(part in IGNORED_PARTS for part in lowered)


def is_sensitive_target(path: str | Path) -> bool:
    path = Path(path)
    lowered_parts = [part.lower() for part in path.parts]
    if path.name.lower() in SECRET_NAMES:
        return True
    short = {"db"}
    return any(
        part in SENSITIVE_PARTS
        or any(token not in short and token in part for token in SENSITIVE_PARTS)
        for part in lowered_parts
    )


def classify_failure(
    *,
    root_cause: str = "",
    error_type: str = "",
    patch_available: bool = False,
    validation_available: bool = False,
    sensitive_target: bool = False,
    exact_match: bool = False,
    multi_file: bool = False,
    external_dependency: bool = False,
) -> str:
    if sensitive_target or external_dependency:
        return "unsafe_blocked"
    if multi_file:
        return "multi_file_required"
    if patch_available and validation_available and exact_match:
        return "deterministic_safe"
    if patch_available and validation_available:
        return "deterministic_with_validation"
    if patch_available:
        return "needs_user_confirmation"
    if error_type in {"MissingEnvironmentVariable", "PortInUse"}:
        return "unsafe_blocked"
    return "suggestion_only"


def compute_confidence(
    *,
    validation_success: bool = False,
    exact_symbol_or_file_match: bool = False,
    rerun_success: bool = False,
    framework_confidence: int = 0,
    parser_confidence: int = 0,
    stacktrace_quality: int = 0,
) -> int:
    score = 10
    if validation_success:
        score += 25
    if exact_symbol_or_file_match:
        score += 20
    if rerun_success:
        score += 25
    score += min(15, max(0, framework_confidence) // 7)
    score += min(15, max(0, parser_confidence) // 7)
    score += min(15, max(0, stacktrace_quality) // 7)
    return max(0, min(100, score))


def structured_plan_from_patch_block(
    patch_block: dict[str, Any] | None,
    *,
    classification: str,
    explanation: str,
    confidence: int,
    command: str = "",
) -> StructuredPatchPlan:
    patch_block = patch_block or {}
    file_path = str(patch_block.get("file_path") or "")
    start = int(patch_block.get("start_line") or 0)
    end = int(patch_block.get("end_line") or start or 0)
    validation = patch_block.get("validation") or "sandbox parser/lint validation"
    strategy = [validation]
    if command:
        strategy.append(f"rerun failing command: {command}")
    return StructuredPatchPlan(
        classification=classification if classification in CLASSIFICATIONS else "suggestion_only",
        file_targets=[file_path] if file_path else [],
        line_ranges=[(start, end)] if start else [],
        explanation=explanation,
        validation_strategy=strategy,
        rollback_metadata={
            "backup_required": True,
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "target": file_path,
        },
        patch_preview=str(patch_block.get("patch") or ""),
        confidence=confidence,
    )


def find_exact_local_symbol(root: str | Path, symbol: str, *, suffixes: set[str] | None = None) -> list[str]:
    if not symbol:
        return []
    root_path = Path(root).resolve()
    matches = []
    wanted_suffixes = suffixes or SUPPORTED_SUFFIXES
    for path in _iter_project_files(root_path, max_files=600):
        if path.suffix.lower() not in wanted_suffixes:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if path.suffix.lower() == ".py":
            if _python_defines_symbol(text, symbol):
                matches.append(_rel(path, root_path))
        elif path.suffix.lower() in JS_TS_SUFFIXES:
            if _js_exports_symbol(text, symbol):
                matches.append(_rel(path, root_path))
        elif path.suffix.lower() == ".php":
            if re.search(rf"\b(class|function)\s+{re.escape(symbol)}\b", text):
                matches.append(_rel(path, root_path))
    return sorted(set(matches))


def record_v07_metric(root: str | Path, metric: str, *, value: int = 1) -> Path:
    allowed = {
        "fix_success_rate",
        "rerun_success_rate",
        "rollback_rate",
        "unsafe_block_rate",
        "unresolved_rate",
        "deterministic_solve_rate",
    }
    root_path = Path(root).resolve()
    path = root_path / ".ghostfix" / "metrics_v07.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    name = metric if metric in allowed else "unresolved_rate"
    path.write_text(
        path.read_text(encoding="utf-8") if path.exists() else "",
        encoding="utf-8",
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": datetime.utcnow().isoformat() + "Z", "metric": name, "value": value}) + "\n")
    return path


def _iter_project_files(root: Path, *, max_files: int) -> Iterable[Path]:
    count = 0
    for path in root.rglob("*"):
        if count >= max_files:
            break
        if not path.is_file():
            continue
        lowered = [part.lower() for part in path.parts]
        if any(part in IGNORED_PARTS for part in lowered):
            continue
        if path.name.lower() in SECRET_NAMES:
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES and path.name not in CONFIG_NAMES and not path.name.startswith("next.config."):
            continue
        count += 1
        yield path


def _index_source_file(graph: DependencyGraph, path: Path, root: Path) -> None:
    rel = _rel(path, root)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    suffix = path.suffix.lower()
    if suffix == ".py":
        graph.imports[rel] = _python_imports(text)
        graph.exports[rel] = _python_exports(text)
        graph.routes[rel] = _python_routes(text)
        graph.components[rel] = []
        graph.entrypoints[rel] = _python_entrypoints(text, rel)
    elif suffix in JS_TS_SUFFIXES:
        graph.imports[rel] = _js_imports(text)
        graph.exports[rel] = _js_exports(text)
        graph.routes[rel] = _js_routes(text, rel)
        graph.components[rel] = _js_components(text, rel)
        graph.entrypoints[rel] = _js_entrypoints(text, rel)
    elif suffix == ".php":
        graph.imports[rel] = _php_imports(text)
        graph.exports[rel] = _php_exports(text)
        graph.routes[rel] = _php_routes(text)
        graph.components[rel] = []
        graph.entrypoints[rel] = []


def _python_imports(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        values = []
        for left, right in re.findall(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", text, re.MULTILINE):
            values.append(left or right)
        return sorted(set(values))
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.append(node.module)
    return sorted(set(values))


def _python_exports(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    exports = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            exports.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    exports.append(target.id)
    return sorted(set(exports))


def _python_routes(text: str) -> list[str]:
    routes = []
    for match in re.finditer(r"@\w+\.(?:route|get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]", text):
        routes.append(match.group(1))
    return sorted(set(routes))


def _python_entrypoints(text: str, rel: str) -> list[str]:
    values = []
    if rel.endswith(("manage.py", "app.py", "main.py", "run.py")):
        values.append(Path(rel).name)
    for match in re.finditer(r"\b(app|api|application)\s*=\s*(?:FastAPI|Flask)\(", text):
        values.append(match.group(1))
    if "if __name__ == \"__main__\"" in text or "if __name__ == '__main__'" in text:
        values.append("__main__")
    return sorted(set(values))


def _js_imports(text: str) -> list[str]:
    values = []
    values.extend(re.findall(r"from\s+['\"]([^'\"]+)['\"]", text))
    values.extend(re.findall(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)", text))
    return sorted(set(values))


def _js_exports(text: str) -> list[str]:
    exports = re.findall(r"export\s+(?:default\s+)?(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)", text)
    exports.extend(re.findall(r"export\s*\{([^}]+)\}", text))
    if re.search(r"export\s+default\b", text):
        exports.append("default")
    flattened = []
    for item in exports:
        flattened.extend(part.strip().split(" as ")[-1] for part in item.split(","))
    return sorted({item for item in flattened if item})


def _js_exports_symbol(text: str, symbol: str) -> bool:
    return symbol in _js_exports(text)


def _js_routes(text: str, rel: str) -> list[str]:
    routes = []
    for match in re.finditer(r"\b(?:app|router)\.(?:get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]", text):
        routes.append(match.group(1))
    api_match = re.search(r"(?:^|/)app/api/(.+?)/route\.[cm]?[jt]s$", rel)
    if api_match:
        routes.append("/api/" + api_match.group(1).replace("\\", "/"))
    return sorted(set(routes))


def _js_components(text: str, rel: str) -> list[str]:
    values = []
    values.extend(re.findall(r"export\s+default\s+function\s+([A-Z][A-Za-z0-9_$]*)", text))
    values.extend(re.findall(r"export\s+(?:function|class)\s+([A-Z][A-Za-z0-9_$]*)", text))
    values.extend(re.findall(r"(?:const|let|var)\s+([A-Z][A-Za-z0-9_$]*)\s*=\s*(?:\([^)]*\)\s*=>|function\b)", text))
    if Path(rel).suffix.lower() in {".jsx", ".tsx"} and re.search(r"export\s+default\b", text):
        values.append(Path(rel).stem)
    return sorted(set(values))


def _js_entrypoints(text: str, rel: str) -> list[str]:
    values = []
    normalized = rel.replace("\\", "/")
    if normalized in {"src/main.tsx", "src/main.jsx", "src/index.tsx", "src/index.jsx", "pages/_app.tsx", "pages/_app.jsx"}:
        values.append(normalized)
    if re.search(r"createRoot\(|ReactDOM\.render\(", text):
        values.append("react-dom")
    if re.search(r"\b(?:app|router)\s*=\s*(?:express\(\)|Router\(\))", text):
        values.append("express")
    if re.search(r"\bapp\.listen\(", text):
        values.append("node-server")
    if re.search(r"(?:^|/)app/(?:page|layout)\.[cm]?[jt]sx?$", normalized):
        values.append("next-app-router")
    if re.search(r"(?:^|/)app/api/.+/route\.[cm]?[jt]s$", normalized):
        values.append("next-api-route")
    return sorted(set(values))


def _php_imports(text: str) -> list[str]:
    return sorted(set(re.findall(r"^\s*use\s+([^;]+);", text, re.MULTILINE)))


def _php_exports(text: str) -> list[str]:
    values = re.findall(r"\b(?:class|interface|trait|function)\s+([A-Za-z_]\w*)", text)
    return sorted(set(values))


def _php_routes(text: str) -> list[str]:
    return sorted(set(re.findall(r"Route::(?:get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]", text)))


def _python_defines_symbol(text: str, symbol: str) -> bool:
    return symbol in _python_exports(text)


def _detect_frameworks(root: Path, snapshot: RepoSnapshot) -> list[str]:
    haystack = " ".join([*snapshot.config_files, *snapshot.source_files]).lower()
    package_path = root / "package.json"
    if package_path.exists():
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except Exception:
            package = {}
        haystack += " " + json.dumps(package).lower()
    frameworks = []
    if (root / "manage.py").exists() or "django" in haystack:
        frameworks.append("django")
    if "fastapi" in haystack or "uvicorn" in haystack:
        frameworks.append("fastapi")
    if "flask" in haystack:
        frameworks.append("flask")
    if "next" in haystack or any(Path(name).name.startswith("next.config") for name in snapshot.config_files):
        frameworks.append("next.js")
    if "vite" in haystack:
        frameworks.append("vite")
    if "react" in haystack:
        frameworks.append("react")
    if "express" in haystack:
        frameworks.append("express")
    if "typescript" in haystack or "tsconfig.json" in snapshot.config_files:
        frameworks.append("typescript")
    if "package.json" in snapshot.config_files:
        frameworks.append("node")
    if any(name.endswith(".php") for name in snapshot.source_files):
        frameworks.append("php/laravel" if "laravel" in haystack or "artisan" in haystack else "php")
    return sorted(set(frameworks), key=frameworks.index)


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
