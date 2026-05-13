from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.context import extract_context
from core.parser import parse_error
from core.project_context import ProjectContext, scan_project_context


@dataclass
class DebugEvidence:
    raw_traceback: str
    error_type: str
    error_message: str
    file_path: Optional[str]
    line_number: Optional[int]
    code_context: Dict[str, Any] = field(default_factory=dict)
    failing_line: str = ""
    symbol: Optional[str] = None
    imports: List[str] = field(default_factory=list)
    nearby_functions: List[str] = field(default_factory=list)
    local_names_before_line: List[str] = field(default_factory=list)
    missing_name: Optional[str] = None
    framework: str = ""
    project_context: ProjectContext | None = None
    evidence: List[str] = field(default_factory=list)
    suggested_fix: str = ""
    source: str = "fallback"
    frames: List[dict] = field(default_factory=list)
    confidence: int = 0
    root_cause: str = "Low confidence: needs manual review."
    likely_root_cause: str = ""
    model_prompt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_traceback": self.raw_traceback,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "code_context": self.code_context,
            "failing_line": self.failing_line,
            "symbol": self.symbol,
            "imports": self.imports,
            "nearby_functions": self.nearby_functions,
            "local_names_before_line": self.local_names_before_line,
            "missing_name": self.missing_name,
            "framework": self.framework,
            "project_context": self.project_context.summary() if self.project_context else "",
            "evidence": self.evidence,
            "suggested_fix": self.suggested_fix,
            "source": self.source,
            "frames": self.frames,
            "confidence": self.confidence,
            "root_cause": self.root_cause,
            "likely_root_cause": self.likely_root_cause,
            "model_prompt": self.model_prompt,
        }


class RootCauseAnalyzer:
    """Build evidence for model-backed debugging without inventing causes."""

    def analyze(self, traceback_text: str, cwd: Optional[str] = None, command: str = "") -> DebugEvidence:
        parsed = parse_error(traceback_text) or {}
        frame = self._select_project_frame(parsed.get("frames") or [], cwd)
        file_path = self._resolve_path((frame or {}).get("file") or parsed.get("file"), cwd)
        line_number = (frame or {}).get("line") or parsed.get("line")
        scan_start = file_path if self._is_project_file(file_path, Path(cwd or ".").resolve()) else self._command_python_file(command, cwd)
        project_context = scan_project_context(cwd, command, scan_start or file_path)
        if self._is_django_app_load_error(parsed, project_context) and not self._is_project_file(file_path, Path(cwd or ".").resolve()):
            settings_path, settings_line = self._nearest_settings_location(project_context)
            if settings_path:
                file_path = settings_path
                line_number = settings_line or 1
        context = extract_context(file_path, traceback_text, line_number) if file_path else {}

        evidence = DebugEvidence(
            raw_traceback=traceback_text,
            error_type=parsed.get("type") or "UnknownError",
            error_message=parsed.get("message") or self._last_nonempty_line(traceback_text),
            file_path=file_path,
            line_number=line_number,
            code_context=context,
            symbol=context.get("symbol") if isinstance(context, dict) else None,
            project_context=project_context,
            frames=parsed.get("frames") or [],
        )

        self._enrich_from_file(evidence)
        evidence.framework = self._detect_framework(evidence, command)
        if evidence.framework and evidence.framework not in project_context.frameworks:
            project_context.frameworks = [evidence.framework]
        evidence.root_cause, evidence.confidence = self._explain_from_evidence(evidence)
        evidence.likely_root_cause = self._human_root_cause(evidence)
        evidence.model_prompt = self.build_model_prompt(evidence)
        return evidence

    def build_model_prompt(self, evidence: DebugEvidence) -> str:
        snippet = evidence.code_context.get("snippet") if isinstance(evidence.code_context, dict) else ""
        return f"""You are GhostFix, a local Python debugging AI.
Use only the evidence below. Do not hallucinate. If the evidence is weak, say: Low confidence: needs manual review.

TRACEBACK:
{evidence.raw_traceback}

PARSED:
error_type={evidence.error_type}
error_message={evidence.error_message}
file_path={evidence.file_path}
line_number={evidence.line_number}
failing_line={evidence.failing_line}
symbol={evidence.symbol}
missing_name={evidence.missing_name}

CODE_CONTEXT:
{snippet}

PROJECT_CONTEXT:
framework={evidence.framework}
safe_scan={evidence.project_context.summary() if evidence.project_context else ""}
imports={evidence.imports}
nearby_functions={evidence.nearby_functions}
local_names_before_line={evidence.local_names_before_line}

Return:
ROOT_CAUSE:
FIX:
PATCH_PLAN:
CONFIDENCE:
"""

    def _resolve_path(self, file_path: Optional[str], cwd: Optional[str]) -> Optional[str]:
        if not file_path:
            return None
        path = Path(file_path)
        if cwd and not path.is_absolute():
            candidate = Path(cwd) / file_path
            if candidate.exists():
                return str(candidate)
        if path.exists():
            return str(path)
        return file_path

    def _select_project_frame(self, frames: List[dict], cwd: Optional[str]) -> Optional[dict]:
        if not frames:
            return None
        root = Path(cwd or ".").resolve()
        for frame in reversed(frames):
            file_path = frame.get("file")
            if self._is_project_file(file_path, root):
                return frame
        return frames[-1]

    def _is_project_file(self, file_path: Optional[str], root: Path) -> bool:
        if not file_path:
            return False
        if file_path.startswith("<"):
            return False
        path = Path(file_path)
        if not path.is_absolute():
            path = root / path
        try:
            resolved = path.resolve()
        except OSError:
            return False
        lowered = str(resolved).lower()
        if any(part in lowered for part in ("site-packages", "<frozen", "\\lib\\", "/lib/", "\\venv\\", "/venv/", "\\.venv\\", "/.venv/")):
            return False
        if not resolved.exists():
            return False
        return resolved == root or root in resolved.parents

    def _command_python_file(self, command: str, cwd: Optional[str]) -> Optional[str]:
        root = Path(cwd or ".").resolve()
        for token in re.findall(r'"([^"]+\.py)"|(\S+\.py)', command or ""):
            value = token[0] or token[1]
            path = Path(value)
            if not path.is_absolute():
                path = root / path
            if path.exists():
                return str(path)
        return None

    def _is_django_app_load_error(self, parsed: dict, project_context: ProjectContext) -> bool:
        if (parsed.get("type") or "") not in {"ModuleNotFoundError", "ImportError"}:
            return False
        raw = (parsed.get("raw") or "").lower()
        return ("apps.populate" in raw or ("django" in raw and "apps" in raw and "populate" in raw)) and (
            "django" in project_context.frameworks or bool(project_context.django_settings)
        )

    def _nearest_settings_location(self, project_context: ProjectContext) -> tuple[Optional[str], Optional[int]]:
        if not project_context.django_settings:
            return None, None
        settings_rel = project_context.django_settings[0]
        settings_path = Path(project_context.root) / settings_rel
        content = project_context.files.get(settings_rel, "")
        for index, line in enumerate(content.splitlines(), start=1):
            if "INSTALLED_APPS" in line:
                return str(settings_path), index
        return str(settings_path), 1

    def _enrich_from_file(self, evidence: DebugEvidence) -> None:
        if not evidence.file_path or not evidence.line_number:
            return

        path = Path(evidence.file_path)
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            return

        lines = text.splitlines()
        index = evidence.line_number - 1
        if 0 <= index < len(lines):
            evidence.failing_line = lines[index].strip()
        elif not evidence.failing_line and isinstance(evidence.code_context, dict):
            evidence.failing_line = str(evidence.code_context.get("failing_line") or "")

        try:
            tree = ast.parse(text)
        except SyntaxError:
            evidence.imports = self._imports_from_text(lines)
            return

        evidence.imports = self._imports_from_ast(tree)
        evidence.nearby_functions = self._functions_from_ast(tree)
        evidence.local_names_before_line = self._names_before_line(tree, evidence.line_number)
        evidence.missing_name = self._extract_missing_name(evidence.error_message)

    def _detect_framework(self, evidence: DebugEvidence, command: str) -> str:
        file_signals = "\n".join([*evidence.imports, evidence.failing_line]).lower()
        if "flask" in file_signals or "render_template" in file_signals:
            return "flask"
        if "fastapi" in file_signals or "uvicorn" in file_signals:
            return "fastapi"
        if "django" in file_signals or Path(evidence.file_path or "").name in {"manage.py", "settings.py"}:
            return "django"

        command_lower = command.lower()
        if "flask" in command_lower:
            return "flask"
        if "uvicorn" in command_lower or "fastapi" in command_lower:
            return "fastapi"
        if "manage.py" in command_lower or "django" in command_lower:
            return "django"

        frame_text = "\n".join(str(frame.get("file", "")) for frame in evidence.frames).lower()
        if "flask" in frame_text or "jinja2" in frame_text:
            return "flask"
        if "uvicorn" in frame_text or "fastapi" in frame_text or "starlette" in frame_text:
            return "fastapi"
        if "django" in frame_text:
            return "django"

        return evidence.project_context.frameworks[0] if evidence.project_context and evidence.project_context.frameworks else ""

    def _explain_from_evidence(self, evidence: DebugEvidence) -> tuple[str, int]:
        parts = []
        if evidence.file_path and evidence.line_number:
            parts.append(f"traceback points to {evidence.file_path} line {evidence.line_number}")
        if evidence.failing_line:
            parts.append(f"code context contains `{evidence.failing_line}`")
        if evidence.framework:
            parts.append(f"framework detected as {evidence.framework}")
        if evidence.project_context and evidence.project_context.summary():
            parts.append(f"safe project scan found {evidence.project_context.summary()}")
        self._attach_framework_evidence(evidence, parts)
        evidence.evidence = parts

        if evidence.framework == "django":
            cause, fix, confidence = self._django_explanation(evidence, parts)
            if cause:
                evidence.source = "framework_rule"
                evidence.suggested_fix = fix
                return cause, confidence

        if evidence.framework == "flask":
            cause, fix, confidence = self._flask_explanation(evidence, parts)
            if cause:
                evidence.source = "framework_rule"
                evidence.suggested_fix = fix
                return cause, confidence

        if evidence.framework == "fastapi":
            cause, fix, confidence = self._fastapi_explanation(evidence, parts)
            if cause:
                evidence.source = "framework_rule"
                evidence.suggested_fix = fix
                return cause, confidence

        if evidence.error_type == "NameError" and evidence.missing_name:
            if evidence.missing_name not in evidence.local_names_before_line:
                cause = (
                    f"The variable `{evidence.missing_name}` is used on line {evidence.line_number} "
                    f"before it is defined. Evidence: {', and '.join(parts)} with no prior assignment "
                    "in the local file context."
                )
                evidence.suggested_fix = f"Define `{evidence.missing_name}` before use or correct its spelling/import."
                evidence.source = "parser"
                return cause, 86 if evidence.failing_line else 62

        if evidence.error_type == "ModuleNotFoundError":
            module = self._extract_missing_module(evidence.error_message)
            if module:
                evidence.suggested_fix = f"Install `{module}` in the active environment or remove/correct the import."
                evidence.source = "parser"
                return (
                    f"The module `{module}` cannot be imported in the active Python environment. "
                    f"Evidence: traceback reports `{evidence.error_message}`.",
                    88,
                )

        if evidence.error_type and evidence.error_type != "UnknownError" and parts:
            evidence.suggested_fix = "Inspect the failing file and line, then rerun the server command after a focused change."
            evidence.source = "parser"
            return (
                f"{evidence.error_type} occurs at the failing expression. Evidence: {', and '.join(parts)}.",
                58,
            )

        evidence.suggested_fix = "Review the traceback and local code context before editing."
        evidence.source = "fallback"
        return "Low confidence: needs manual review.", 20

    def _django_explanation(self, evidence: DebugEvidence, parts: List[str]) -> tuple[str, str, int]:
        if evidence.error_type == "RuntimeError" and "settings already configured" in evidence.error_message.lower():
            return (
                "django_settings_already_configured",
                "Remove duplicate settings.configure() or set DJANGO_SETTINGS_MODULE before Django initializes.",
                90,
            )
        if evidence.error_type == "ImproperlyConfigured":
            return (
                "django_configuration_error",
                "Check settings.py, DJANGO_SETTINGS_MODULE, INSTALLED_APPS, database settings, and required environment-backed settings.",
                82,
            )
        if evidence.error_type in {"ModuleNotFoundError", "ImportError"}:
            module = self._extract_missing_module(evidence.error_message) or "the missing app module"
            if self._traceback_contains(evidence, "apps.populate") or self._settings_mentions_installed_apps(evidence):
                return (
                    "missing_django_app_or_bad_installed_apps",
                    f"Fix `{module}` in INSTALLED_APPS: correct the app path, add the app package to the project, or install the missing Django app dependency.",
                    88,
                )
            return (
                "django_import_error",
                "Verify the app/module name in INSTALLED_APPS, urls.py, wsgi/asgi.py, and installed dependencies.",
                80,
            )
        if evidence.error_type == "TemplateDoesNotExist":
            return (
                "missing_django_template",
                "Create the referenced template under an enabled template directory or correct the template path.",
                86,
            )
        return "", "", 0

    def _human_root_cause(self, evidence: DebugEvidence) -> str:
        if evidence.source != "framework_rule":
            return evidence.root_cause

        module = self._extract_missing_module(evidence.error_message) or "the referenced module"
        template = evidence.error_message.strip() or "the referenced template"
        line = f"line {evidence.line_number}" if evidence.line_number else "the failing line"
        code = evidence.failing_line or "the failing code"

        explanations = {
            "missing_template": (
                f"Flask could not find `{template}`. The call on {line} uses `{code}`, "
                "but no matching file was found in the app's templates folder."
            ),
            "flask_app_context_error": (
                "Flask code is running outside an application context. This usually means app-specific "
                "objects are being accessed before a request, CLI command, or app.app_context() is active."
            ),
            "missing_django_app_or_bad_installed_apps": (
                f"Django failed while populating INSTALLED_APPS because `{module}` could not be imported. "
                "The nearest settings.py lists an app module that is missing, misspelled, or not installed."
            ),
            "django_settings_already_configured": (
                "Django settings were configured more than once in the same process. A second "
                "settings.configure() call ran after Django settings were already initialized."
            ),
            "django_configuration_error": (
                "Django could not start because project settings are incomplete or invalid. "
                "Check the nearest settings.py and DJANGO_SETTINGS_MODULE configuration."
            ),
            "missing_django_template": (
                f"Django could not find `{template}`. The template path does not resolve inside the "
                "configured template directories or app templates folders."
            ),
            "fastapi_app_import_error": (
                f"FastAPI failed while Uvicorn was importing the app. The import on {line} references "
                f"`{module}`, which does not exist or is not available on the Python path."
            ),
            "fastapi_app_object_not_found": (
                "Uvicorn imported the module but could not find the FastAPI app object requested by "
                "the module:app target."
            ),
        }
        return explanations.get(evidence.root_cause, evidence.root_cause)

    def _flask_explanation(self, evidence: DebugEvidence, parts: List[str]) -> tuple[str, str, int]:
        if evidence.error_type == "TemplateNotFound":
            template = evidence.error_message.strip() or "the referenced template"
            return (
                "missing_template",
                f"Create `templates/{template}` in the Flask app, configure the template folder, or correct the path passed to render_template().",
                90,
            )
        if evidence.error_type == "RuntimeError" and "working outside" in evidence.error_message.lower() and "application context" in evidence.error_message.lower():
            return (
                "flask_app_context_error",
                "Run the code inside app.app_context(), a request handler, or a Flask CLI/application factory context.",
                88,
            )
        if evidence.error_type in {"ModuleNotFoundError", "ImportError", "AttributeError"}:
            return (
                "flask_app_import_error",
                "Verify FLASK_APP, the app module, the application variable/factory, and imported dependencies.",
                80,
            )
        return "", "", 0

    def _fastapi_explanation(self, evidence: DebugEvidence, parts: List[str]) -> tuple[str, str, int]:
        if evidence.error_type in {"ModuleNotFoundError", "ImportError"}:
            module = self._extract_missing_module(evidence.error_message) or "the missing module"
            return (
                "fastapi_app_import_error",
                f"Fix the missing startup import `{module}`, verify the Uvicorn module:app target points to the right module, and check imports that run while the FastAPI app starts.",
                82,
            )
        if evidence.error_type == "AttributeError":
            return (
                "fastapi_app_object_not_found",
                "Verify the uvicorn target points to an existing FastAPI app object, for example main:app.",
                84,
            )
        return "", "", 0

    def _attach_framework_evidence(self, evidence: DebugEvidence, parts: List[str]) -> None:
        frame_text = "\n".join(
            f"{frame.get('file', '')}:{frame.get('line', '')} {frame.get('function', '')} {frame.get('code', '')}"
            for frame in evidence.frames
        )
        if evidence.framework == "django":
            if "apps.populate" in frame_text:
                parts.append("traceback includes django apps.populate during app loading")
            if evidence.project_context and evidence.project_context.django_settings:
                parts.append(f"nearest Django settings file: {evidence.project_context.django_settings[0]}")
        if evidence.framework == "flask" and ("render_template" in frame_text or "render_template" in evidence.failing_line):
            parts.append("traceback includes render_template call")
        if evidence.framework == "fastapi" and ("uvicorn" in frame_text.lower() or "fastapi" in frame_text.lower()):
            parts.append("traceback occurred during uvicorn/FastAPI app import")

    def _traceback_contains(self, evidence: DebugEvidence, text: str) -> bool:
        needle = text.lower()
        return needle in evidence.raw_traceback.lower()

    def _settings_mentions_installed_apps(self, evidence: DebugEvidence) -> bool:
        if not evidence.project_context:
            return False
        return any("INSTALLED_APPS" in content for name, content in evidence.project_context.files.items() if name.endswith("settings.py"))

    def _imports_from_ast(self, tree: ast.AST) -> List[str]:
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.extend(f"{module}.{alias.name}".strip(".") for alias in node.names)
        return sorted(set(imports))

    def _imports_from_text(self, lines: List[str]) -> List[str]:
        imports = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                imports.append(stripped)
        return imports

    def _functions_from_ast(self, tree: ast.AST) -> List[str]:
        names = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.append(node.name)
        return sorted(set(names))

    def _names_before_line(self, tree: ast.AST, line_number: int) -> List[str]:
        names = set()
        for node in ast.walk(tree):
            if getattr(node, "lineno", line_number + 1) >= line_number:
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    names.update(self._target_names(target))
            elif isinstance(node, ast.AnnAssign):
                names.update(self._target_names(node.target))
            elif isinstance(node, ast.Import):
                names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.update(alias.asname or alias.name for alias in node.names)
        return sorted(names)

    def _target_names(self, target: ast.AST) -> List[str]:
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, (ast.Tuple, ast.List)):
            names = []
            for item in target.elts:
                names.extend(self._target_names(item))
            return names
        return []

    def _extract_missing_name(self, message: str) -> Optional[str]:
        match = re.search(r"name ['\"]([^'\"]+)['\"] is not defined", message or "")
        return match.group(1) if match else None

    def _extract_missing_module(self, message: str) -> Optional[str]:
        match = re.search(r"No module named ['\"]([^'\"]+)['\"]", message or "")
        return match.group(1) if match else None

    def _last_nonempty_line(self, text: str) -> str:
        for line in reversed((text or "").splitlines()):
            if line.strip():
                return line.strip()
        return ""
