from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.framework_fixer import build_framework_patch_plan, patch_block_from_framework_plan
from core.iterative_agent import iterative_validate_patch
from core.js_autofix import build_js_patch_plan, patch_block_from_plan
from core.repo_engine import build_repo_snapshot, compute_confidence, is_sensitive_target


MAX_REPAIR_LOOPS = 3
MAX_CANDIDATES = 3
SUPPORTED_STACKS = {"python", "django", "flask", "fastapi", "express", "node", "next.js", "react", "vite", "vite/react", "typescript"}


@dataclass
class ToolTrace:
    tool: str
    target: str
    ok: bool
    detail: str = ""
    latency_ms: int = 0


@dataclass
class PatchCandidate:
    name: str
    patch_block: dict[str, Any]
    confidence: int
    repo_consistency: int = 0
    validation_success: bool = False
    regression_score: int = 100
    rerun_output_quality: int = 0
    validation_latency_ms: int = 0
    validation_reason: str = ""
    retry_count: int = 0
    ranking_score: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AutonomousRepairResult:
    ok: bool
    reason: str
    patch_block: dict[str, Any] = field(default_factory=dict)
    candidates: list[PatchCandidate] = field(default_factory=list)
    tool_trace: list[ToolTrace] = field(default_factory=list)
    repo_graph: dict[str, Any] = field(default_factory=dict)
    telemetry: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        payload["tool_trace"] = [asdict(item) for item in self.tool_trace]
        return payload


class BoundedToolExecutionEngine:
    """Read and rerun project context in a temporary sandbox only."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.tool_trace: list[ToolTrace] = []
        self._temp: tempfile.TemporaryDirectory[str] | None = None
        self.sandbox_root: Path | None = None

    def __enter__(self) -> "BoundedToolExecutionEngine":
        self._temp = tempfile.TemporaryDirectory(prefix="ghostfix_agent_")
        self.sandbox_root = Path(self._temp.name) / self.root.name
        ignore = shutil.ignore_patterns(".git", ".ghostfix", ".next", "node_modules", "dist", "build", "coverage", "__pycache__", ".pytest_cache", ".venv", "venv")
        shutil.copytree(self.root, self.sandbox_root, ignore=ignore)
        self._record("sandbox.copy", str(self.sandbox_root), True)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._temp:
            self._temp.cleanup()

    def build_graph(self) -> dict[str, Any]:
        start = time.perf_counter()
        snapshot = build_repo_snapshot(self.sandbox_root or self.root)
        self._record("repo.graph", snapshot.root, True, snapshot.summary(), start)
        return {
            "root": snapshot.root,
            "frameworks": snapshot.frameworks,
            "config_files": snapshot.config_files,
            "source_files": snapshot.source_files,
            "imports": snapshot.graph.imports,
            "exports": snapshot.graph.exports,
            "routes": snapshot.graph.routes,
            "components": snapshot.graph.components,
            "entrypoints": snapshot.graph.entrypoints,
        }

    def inspect_package_json(self) -> dict[str, Any]:
        return self._read_json("package.json", "inspect.package_json")

    def inspect_tsconfig(self) -> dict[str, Any]:
        return self._read_json("tsconfig.json", "inspect.tsconfig")

    def rerun(self, command: str, *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        start = time.perf_counter()
        try:
            result = subprocess.run(command, cwd=str(self.sandbox_root or self.root), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        except Exception as exc:
            result = subprocess.CompletedProcess(command, 1, stdout="", stderr=str(exc))
        self._record("rerun.command", command, result.returncode == 0, (result.stderr or result.stdout or "")[:300], start)
        return result

    def _read_json(self, rel: str, tool: str) -> dict[str, Any]:
        start = time.perf_counter()
        path = (self.sandbox_root or self.root) / rel
        if not path.exists():
            self._record(tool, rel, False, "missing", start)
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._record(tool, rel, False, str(exc), start)
            return {}
        self._record(tool, rel, True, "ok", start)
        return payload if isinstance(payload, dict) else {}

    def _record(self, tool: str, target: str, ok: bool, detail: str = "", start: float | None = None) -> None:
        latency = int((time.perf_counter() - start) * 1000) if start else 0
        self.tool_trace.append(ToolTrace(tool=tool, target=target, ok=ok, detail=detail, latency_ms=latency))


class AutonomousDebuggingAgent:
    def __init__(self, *, cwd: str | Path | None = None, command: str = "", max_loops: int = MAX_REPAIR_LOOPS):
        self.cwd = Path(cwd or ".").resolve()
        self.command = command
        self.max_loops = max(1, min(max_loops, MAX_REPAIR_LOOPS))

    def repair(self, diagnostic: dict[str, Any]) -> AutonomousRepairResult:
        framework = diagnostic.get("framework") or ""
        if framework not in SUPPORTED_STACKS:
            return self._blocked(f"Unsupported stack for autonomous repair: {framework}")
        if _diagnostic_is_sensitive(diagnostic):
            return self._blocked("Autonomous repair is blocked for auth, payment, database, secret, deployment, infrastructure, or security-sensitive failures.")

        with BoundedToolExecutionEngine(self.cwd) as tools:
            repo_graph = tools.build_graph()
            tools.inspect_package_json()
            tools.inspect_tsconfig()
            candidates = self._generate_candidates(diagnostic, repo_graph)
            ranked = self._validate_and_rank(diagnostic, candidates)
            winner = next((candidate for candidate in ranked if candidate.validation_success and candidate.regression_score >= 80), None)
            telemetry = _telemetry(ranked, winner)
            telemetry["tool_trace_count"] = len(tools.tool_trace)
            if not winner:
                return AutonomousRepairResult(False, "No candidate passed validation without regression.", candidates=ranked, tool_trace=tools.tool_trace, repo_graph=repo_graph, telemetry=telemetry)
            patch_block = winner.patch_block
            if not patch_block.get("files"):
                return AutonomousRepairResult(False, "Validated candidate did not include rollback-capable file metadata.", candidates=ranked, tool_trace=tools.tool_trace, repo_graph=repo_graph, telemetry=telemetry)
            return AutonomousRepairResult(True, "Autonomous repair converged after sandbox validation.", patch_block=patch_block, candidates=ranked, tool_trace=tools.tool_trace, repo_graph=repo_graph, telemetry=telemetry)

    def _generate_candidates(self, diagnostic: dict[str, Any], repo_graph: dict[str, Any]) -> list[PatchCandidate]:
        blocks: list[tuple[str, dict[str, Any], int]] = []
        seed = diagnostic.get("patch_block") or {}
        if seed.get("available"):
            blocks.append(("diagnostic_patch", seed, int(diagnostic.get("confidence") or 70)))

        framework_plan = build_framework_patch_plan(diagnostic, cwd=str(self.cwd))
        if framework_plan.available:
            blocks.append(("framework_planner", patch_block_from_framework_plan(framework_plan), 88))

        js_plan = build_js_patch_plan(diagnostic, cwd=str(self.cwd))
        if js_plan.available:
            blocks.append(("js_ts_planner", patch_block_from_plan(js_plan), 78))

        python_plan = _python_candidate(diagnostic, self.cwd)
        if python_plan.get("available"):
            blocks.append(("python_framework_planner", python_plan, 80))

        candidates: list[PatchCandidate] = []
        seen: set[str] = set()
        for name, block, confidence in blocks:
            key = json.dumps({k: block.get(k) for k in ("action", "file_path", "start_line", "end_line", "replacement", "files")}, sort_keys=True, default=str)
            if key in seen or _has_sensitive_targets(block):
                continue
            seen.add(key)
            candidates.append(PatchCandidate(name=name, patch_block=block, confidence=confidence, repo_consistency=_repo_consistency(block, repo_graph)))
            if len(candidates) >= MAX_CANDIDATES:
                break
        return candidates

    def _validate_and_rank(self, diagnostic: dict[str, Any], candidates: list[PatchCandidate]) -> list[PatchCandidate]:
        command = self.command or _validation_command_for(self.cwd, diagnostic)
        for candidate in candidates[:MAX_CANDIDATES]:
            start = time.perf_counter()
            result = iterative_validate_patch(diagnostic, candidate.patch_block, command=command, cwd=str(self.cwd), max_retries=self.max_loops)
            candidate.validation_latency_ms = int((time.perf_counter() - start) * 1000)
            candidate.validation_success = result.ok
            candidate.validation_reason = result.reason
            candidate.retry_count = max(0, len(result.telemetry) - 1)
            candidate.regression_score = 0 if result.regression_detected else 100
            candidate.rerun_output_quality = 100 if result.ok else (35 if result.telemetry else 0)
            candidate.confidence = max(candidate.confidence, result.confidence)
            if result.ok:
                candidate.patch_block = result.patch_block
            candidate.ranking_score = _ranking_score(candidate)
        return sorted(candidates, key=lambda item: item.ranking_score, reverse=True)

    def _blocked(self, reason: str) -> AutonomousRepairResult:
        return AutonomousRepairResult(False, reason, telemetry={"convergence_result": "blocked", "final_confidence": 0})


def repair_autonomously(diagnostic: dict[str, Any], *, cwd: str | Path | None = None, command: str = "", max_loops: int = MAX_REPAIR_LOOPS) -> AutonomousRepairResult:
    return AutonomousDebuggingAgent(cwd=cwd, command=command, max_loops=max_loops).repair(diagnostic)


def _python_candidate(diagnostic: dict[str, Any], root: Path) -> dict[str, Any]:
    if diagnostic.get("framework") not in {"python", "django", "flask", "fastapi"}:
        return {}
    path = Path(diagnostic.get("file") or "")
    if not path.is_absolute():
        path = root / path
    if not path.exists() or path.suffix != ".py" or is_sensitive_target(path):
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    command = str(diagnostic.get("command") or "")
    if diagnostic.get("framework") == "fastapi" and "uvicorn" in command or diagnostic.get("root_cause") == "fastapi_wrong_app_object":
        match = re.search(r"^(\s*)api\s*=\s*FastAPI\(\)", text, re.MULTILINE)
        if match and "app = FastAPI()" not in text:
            line = text[: match.start()].count("\n") + 1
            return _line_patch(path, text, line, f"{match.group(1)}app = FastAPI()\n", "python", "fastapi", "Rename FastAPI object to app for the uvicorn entrypoint.")
    if diagnostic.get("root_cause") == "missing_import" and diagnostic.get("symbol"):
        symbol = str(diagnostic["symbol"])
        if symbol == "FastAPI" and "from fastapi import FastAPI" not in text:
            return _prepend_patch(path, text, "from fastapi import FastAPI\n", diagnostic.get("framework") or "fastapi", "Add missing FastAPI import.")
        if symbol == "Flask" and "from flask import Flask" not in text:
            return _prepend_patch(path, text, "from flask import Flask\n", diagnostic.get("framework") or "flask", "Add missing Flask import.")
    return {}


def _line_patch(path: Path, text: str, line: int, replacement: str, language: str, framework: str, reason: str) -> dict[str, Any]:
    import difflib

    old_lines = text.splitlines(keepends=True)
    new_lines = old_lines[:]
    new_lines[line - 1:line] = [replacement]
    return {
        "available": True,
        "file_path": str(path),
        "start_line": line,
        "end_line": line,
        "replacement": replacement,
        "patch": "".join(difflib.unified_diff(old_lines, new_lines, fromfile=str(path), tofile=str(path), lineterm="\n")),
        "language": language,
        "framework": framework,
        "reason": reason,
    }


def _prepend_patch(path: Path, text: str, insertion: str, framework: str, reason: str) -> dict[str, Any]:
    first_line = text.splitlines(keepends=True)[:1] or [""]
    return _line_patch(path, text, 1, insertion + first_line[0], "python", framework, reason)


def _repo_consistency(block: dict[str, Any], repo_graph: dict[str, Any]) -> int:
    source_files = set(repo_graph.get("source_files") or [])
    config_files = set(repo_graph.get("config_files") or [])
    root = Path(repo_graph.get("root") or ".").resolve()
    paths = [item.get("file_path", "") for item in block.get("files") or []] or [block.get("file_path", "")]
    if not paths:
        return 0
    score = 40
    for value in paths:
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        try:
            rel = path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        if rel in source_files or rel in config_files or path.name == ".env.example":
            score += 20
    return min(100, score)


def _ranking_score(candidate: PatchCandidate) -> int:
    score = 0
    score += 40 if candidate.validation_success else 0
    score += candidate.regression_score // 5
    score += candidate.confidence // 5
    score += candidate.repo_consistency // 5
    score += candidate.rerun_output_quality // 5
    return max(0, min(100, score))


def _telemetry(candidates: list[PatchCandidate], winner: PatchCandidate | None) -> dict[str, Any]:
    return {
        "retry_count": winner.retry_count if winner else max((candidate.retry_count for candidate in candidates), default=0),
        "convergence_result": "converged" if winner else "unresolved",
        "regression_result": "passed" if winner else ("failed" if any(candidate.regression_score == 0 for candidate in candidates) else "not_converged"),
        "validation_latency_ms": sum(candidate.validation_latency_ms for candidate in candidates),
        "candidate_ranking": [
            {
                "name": candidate.name,
                "score": candidate.ranking_score,
                "validation_success": candidate.validation_success,
                "regression_score": candidate.regression_score,
                "confidence": candidate.confidence,
            }
            for candidate in candidates
        ],
        "final_confidence": winner.confidence if winner else 0,
    }


def _validation_command_for(root: Path, diagnostic: dict[str, Any]) -> str:
    framework = diagnostic.get("framework") or ""
    if framework in {"next.js", "react", "vite", "vite/react", "typescript", "express", "node"}:
        package = root / "package.json"
        if package.exists():
            try:
                data = json.loads(package.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            if isinstance(data.get("scripts"), dict) and "build" in data["scripts"]:
                return "npm run build"
        if (root / "tsconfig.json").exists():
            return "tsc --noEmit"
    file_name = Path(diagnostic.get("file") or "").name
    if file_name.endswith(".py"):
        return f"python -m py_compile {file_name}"
    return ""


def _diagnostic_is_sensitive(diagnostic: dict[str, Any]) -> bool:
    root_cause = str(diagnostic.get("root_cause") or "").lower()
    message = str(diagnostic.get("message") or "").lower()
    blocked_tokens = ("auth", "oauth", "login", "session", "payment", "billing", "migration", "schema", "secret", ".env", "deploy", "infrastructure", "security")
    return any(token in root_cause or token in message for token in blocked_tokens) or is_sensitive_target(diagnostic.get("file") or "")


def _has_sensitive_targets(block: dict[str, Any]) -> bool:
    files = block.get("files") or []
    if files:
        return any(is_sensitive_target(item.get("file_path", "")) for item in files)
    return is_sensitive_target(block.get("file_path", ""))
