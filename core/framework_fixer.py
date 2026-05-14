from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


JS_TS_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
SENSITIVE_PARTS = {"auth", "login", "oauth", "session", "payment", "billing", "database", "db", "security", "secret", "deploy", "infra"}
BLOCKED_ENV_NAMES = {".env", ".env.local", ".env.production", ".env.development"}


@dataclass
class FilePatch:
    file_path: str
    old_text: str
    new_text: str
    reason: str

    def preview(self) -> str:
        return "".join(
            difflib.unified_diff(
                _preview_lines(self.old_text),
                _preview_lines(self.new_text),
                fromfile=self.file_path,
                tofile=self.file_path,
                lineterm="\n",
            )
        )


@dataclass
class FrameworkPatchPlan:
    available: bool
    reason: str
    patches: list[FilePatch] = field(default_factory=list)
    validation_commands: list[list[str]] = field(default_factory=list)
    route: str = ""
    framework: str = ""

    @property
    def preview(self) -> str:
        return "\n".join(patch.preview() for patch in self.patches if patch.preview())


def build_framework_patch_plan(diagnostic: dict[str, Any], cwd: str | None = None) -> FrameworkPatchPlan:
    if diagnostic.get("root_cause") == "ollama_connection_failed" and diagnostic.get("framework") == "next.js":
        return _next_ollama_guard_plan(diagnostic, Path(cwd or ".").resolve())
    return FrameworkPatchPlan(False, "No framework-safe patch planner matched this diagnostic.")


def patch_block_from_framework_plan(plan: FrameworkPatchPlan) -> dict[str, Any]:
    first_file = plan.patches[0].file_path if plan.patches else ""
    return {
        "available": plan.available,
        "action": "framework_multi_file",
        "reason": plan.reason,
        "file_path": first_file,
        "files": [
            {
                "file_path": patch.file_path,
                "old_text": patch.old_text,
                "new_text": patch.new_text,
                "reason": patch.reason,
            }
            for patch in plan.patches
        ],
        "patch": plan.preview,
        "validation": "temporary project copy + npm run build",
        "validation_commands": plan.validation_commands,
        "language": "javascript/typescript",
        "framework": plan.framework,
        "route": plan.route,
        "requires_project_validation": True,
    }


def _next_ollama_guard_plan(diagnostic: dict[str, Any], root: Path) -> FrameworkPatchPlan:
    route = diagnostic.get("route") or ""
    route_file = _route_file_for_route(root, route)
    if not route_file:
        return FrameworkPatchPlan(False, f"No exact local Next.js route file was found for route `{route}`.")
    if _is_sensitive_path(route_file):
        return FrameworkPatchPlan(False, "Route target is blocked by safety policy.")

    agent_file = _resolve_resume_agent(root, route_file)
    if not agent_file:
        return FrameworkPatchPlan(False, "Could not identify the local resumeAgent source file from the route/import graph.")
    if _is_sensitive_path(agent_file):
        return FrameworkPatchPlan(False, "Ollama agent target is blocked by safety policy.")

    try:
        agent_text = agent_file.read_text(encoding="utf-8")
    except OSError as exc:
        return FrameworkPatchPlan(False, f"Could not read Ollama agent file: {exc}")
    if "OLLAMA_BASE_URL" not in agent_text or "fetch" not in agent_text:
        return FrameworkPatchPlan(False, "Ollama agent file does not contain an obvious OLLAMA_BASE_URL fetch path.")
    if "preflightOllama" in agent_text or "OLLAMA_TIMEOUT_MS" in agent_text:
        return FrameworkPatchPlan(False, "Ollama guard already appears to exist; manual review recommended.")

    new_agent_text = _patch_resume_agent(agent_text)
    if new_agent_text == agent_text:
        return FrameworkPatchPlan(False, "Could not build a narrow Ollama guard patch for this source shape.")

    patches = [
        FilePatch(
            file_path=str(agent_file),
            old_text=agent_text,
            new_text=new_agent_text,
            reason="Add Ollama preflight, model check, timeout, and clearer route-safe errors.",
        )
    ]

    env_example = root / ".env.example"
    env_old = env_example.read_text(encoding="utf-8") if env_example.exists() else ""
    env_new = _patch_env_example(env_old)
    if env_new != env_old:
        patches.append(
            FilePatch(
                file_path=str(env_example),
                old_text=env_old,
                new_text=env_new,
                reason="Document safe non-secret Ollama environment defaults in .env.example only.",
            )
        )

    if any(Path(patch.file_path).name in BLOCKED_ENV_NAMES for patch in patches):
        return FrameworkPatchPlan(False, "Patch attempted to modify a blocked .env file.")

    return FrameworkPatchPlan(
        True,
        "Safe Next.js Ollama route guard patch with project build validation.",
        patches=patches,
        validation_commands=[["npm", "run", "build"]],
        route=route,
        framework="next.js",
    )


def _route_file_for_route(root: Path, route: str) -> Path | None:
    if not route.startswith("/api/"):
        return None
    route_parts = route.strip("/").split("/")
    candidates = []
    for base in (root / "app", root / "src" / "app"):
        candidates.extend(base.joinpath(*route_parts).glob("route.*"))
    exact = [path.resolve() for path in candidates if path.suffix.lower() in JS_TS_SUFFIXES and path.is_file()]
    return exact[0] if len(exact) == 1 else None


def _resolve_resume_agent(root: Path, route_file: Path) -> Path | None:
    try:
        route_text = route_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        route_text = ""
    import_targets = re.findall(r"from\s+['\"]([^'\"]*resumeAgent[^'\"]*)['\"]", route_text)
    import_targets += re.findall(r"require\(['\"]([^'\"]*resumeAgent[^'\"]*)['\"]\)", route_text)
    for target in import_targets:
        resolved = _resolve_ts_module(root, route_file.parent, target)
        if resolved:
            return resolved
    matches = [path.resolve() for path in root.rglob("resumeAgent.*") if path.suffix.lower() in JS_TS_SUFFIXES and _is_safe_project_file(path, root)]
    return matches[0] if len(matches) == 1 else None


def _resolve_ts_module(root: Path, base: Path, target: str) -> Path | None:
    if target.startswith("@/"):
        direct = root / target[2:]
    elif target.startswith("."):
        direct = base / target
    else:
        return None
    candidates = [direct.with_suffix(suffix) for suffix in JS_TS_SUFFIXES]
    candidates += [direct / f"index{suffix}" for suffix in JS_TS_SUFFIXES]
    exact = [candidate.resolve() for candidate in candidates if candidate.exists() and candidate.is_file()]
    exact = [candidate for candidate in exact if _is_safe_project_file(candidate, root)]
    return exact[0] if len(exact) == 1 else None


def _patch_resume_agent(text: str) -> str:
    helper = """

const DEFAULT_OLLAMA_TIMEOUT_MS = 30000;

function ollamaTimeoutMs(): number {
  const parsed = Number(process.env.OLLAMA_TIMEOUT_MS || DEFAULT_OLLAMA_TIMEOUT_MS);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_OLLAMA_TIMEOUT_MS;
}

function ollamaError(message: string): Error {
  return new Error(`[GhostFix] ${message}`);
}

async function fetchOllamaJson(path: string, init: RequestInit = {}) {
  const baseUrl = process.env.OLLAMA_BASE_URL || "http://localhost:11434";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), ollamaTimeoutMs());
  try {
    const response = await fetch(`${baseUrl}${path}`, {
      ...init,
      signal: controller.signal,
    });
    return response;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw ollamaError(`Could not connect to Ollama at ${baseUrl}. Check OLLAMA_BASE_URL and make sure Ollama is running. Details: ${detail}`);
  } finally {
    clearTimeout(timeout);
  }
}

async function preflightOllama(requiredModel?: string) {
  const tagsResponse = await fetchOllamaJson("/api/tags");
  if (!tagsResponse.ok) {
    throw ollamaError(`Ollama health check failed with HTTP ${tagsResponse.status}.`);
  }
  const tags = await tagsResponse.json().catch(() => ({ models: [] }));
  const models = Array.isArray(tags.models) ? tags.models : [];
  if (requiredModel && !models.some((model: any) => model?.name === requiredModel || model?.model === requiredModel)) {
    throw ollamaError(`Ollama model "${requiredModel}" is not installed. Run "ollama pull ${requiredModel}" manually, then retry.`);
  }
}
""".strip("\n")

    insertion = _helper_insert_index(text)
    lines = text.splitlines(keepends=True)
    lines[insertion:insertion] = [helper + "\n\n"]
    patched = "".join(lines)
    model_name = _model_expression(patched)
    call = f"  await preflightOllama({model_name});\n" if model_name else "  await preflightOllama();\n"
    fetch_index = _first_ollama_fetch_line(patched)
    if fetch_index < 0:
        return text
    patched_lines = patched.splitlines(keepends=True)
    if not any("preflightOllama" in line for line in patched_lines[max(0, fetch_index - 8):fetch_index]):
        patched_lines[fetch_index:fetch_index] = [call]
    patched = "".join(patched_lines)
    patched = _replace_fetch_base_url(patched)
    return patched


def _helper_insert_index(text: str) -> int:
    lines = text.splitlines(keepends=True)
    index = 0
    for offset, line in enumerate(lines):
        if line.startswith("import ") or line.startswith("export type ") or line.startswith("type "):
            index = offset + 1
            continue
        if not line.strip():
            index = offset + 1
            continue
        break
    return index


def _model_expression(text: str) -> str:
    env_match = re.search(r"const\s+([A-Za-z_$][\w$]*)\s*=\s*process\.env\.OLLAMA_MODEL\b", text)
    if env_match:
        return env_match.group(1)
    const_match = re.search(r"const\s+([A-Za-z_$][\w$]*)\s*=\s*['\"]([^'\"]+)['\"]", text)
    if const_match and re.search(r"model\s*:\s*" + re.escape(const_match.group(1)), text):
        return const_match.group(1)
    literal_match = re.search(r"model\s*:\s*['\"]([^'\"]+)['\"]", text)
    if literal_match:
        return json.dumps(literal_match.group(1))
    return ""


def _first_ollama_fetch_line(text: str) -> int:
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if "fetch(" in line and ("OLLAMA_BASE_URL" in line or "ollama" in line.lower() or "baseUrl" in line):
            return index
    for index, line in enumerate(lines):
        if "fetch(" in line:
            return index
    return -1


def _replace_fetch_base_url(text: str) -> str:
    text = re.sub(
        r"fetch\(\s*`\$\{(?:process\.env\.OLLAMA_BASE_URL\s*\|\|\s*['\"]http://localhost:11434['\"]|OLLAMA_BASE_URL|ollamaBaseUrl|baseUrl)\}(/api/[^`]+)`",
        r"fetchOllamaJson(\"\1\"",
        text,
        count=1,
    )
    text = re.sub(
        r"fetch\(\s*(?:process\.env\.OLLAMA_BASE_URL\s*\+\s*)?['\"](/api/[^'\"]+)['\"]",
        r"fetchOllamaJson(\"\1\"",
        text,
        count=1,
    )
    return text


def _patch_env_example(text: str) -> str:
    lines = text.splitlines()
    existing = {line.split("=", 1)[0].strip() for line in lines if "=" in line and not line.lstrip().startswith("#")}
    additions = []
    if "OLLAMA_BASE_URL" not in existing:
        additions.append("OLLAMA_BASE_URL=http://localhost:11434")
    if "OLLAMA_MODEL" not in existing:
        additions.append("OLLAMA_MODEL=llama3")
    if "OLLAMA_TIMEOUT_MS" not in existing:
        additions.append("OLLAMA_TIMEOUT_MS=30000")
    if not additions:
        return text
    prefix = text.rstrip("\n")
    if prefix:
        prefix += "\n"
    return prefix + "\n".join(additions) + "\n"


def _is_sensitive_path(path: Path) -> bool:
    lowered = [part.lower() for part in path.parts]
    if path.name.lower() in BLOCKED_ENV_NAMES:
        return True
    return any(part in SENSITIVE_PARTS or any(token in part for token in SENSITIVE_PARTS) for part in lowered)


def _is_safe_project_file(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    lowered = [part.lower() for part in path.parts]
    return not any(part in {".git", ".next", "node_modules", "dist", "build", ".ghostfix"} for part in lowered)


def _preview_lines(text: str) -> list[str]:
    return [line if line.endswith("\n") else f"{line}\n" for line in text.splitlines(keepends=True)]
