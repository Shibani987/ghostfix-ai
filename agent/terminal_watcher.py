from __future__ import annotations

import subprocess
import sys
import hashlib
import re
import difflib
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

from core.autofix import build_patch_plan
from core.command_rerunner import rerun_command
from core.confidence import confidence_percent
from core.decision_engine import apply_safety_policy, decide_fix
from core.fix_audit import record_fix_audit
from core.formatter import show_output
from core.incidents import make_incident, record_incident
from core.language_diagnostics import detect_language, diagnose_non_python
from core.log_events import LogEventKind, LogEventPipeline, LogSourceType
from core.patch_validator import PatchValidator
from core.parser import extract_runtime_error
from core.repo_engine import classify_failure, compute_confidence, is_sensitive_target, record_v07_metric, structured_plan_from_patch_block
from core.root_cause_analyzer import RootCauseAnalyzer
from core.runtime_detector import infer_runtime_profile
from core.tooling_diagnostics import diagnose_tooling
from ml.feedback_logger import log_decision_feedback


console = Console()
MAX_TRACEBACK_CAPTURE_SIZE = 64_000
MAX_HANDLED_TRACEBACK_KEYS = 256
MAX_REPEATED_DUPLICATE_TRACEBACKS = 25
MAX_STREAM_BUFFER_SIZE = 128_000
MAX_STREAM_EVENT_SIZE = 32_000
MAX_RUNTIME_LOG_LINES = 60
MAX_HANDLED_LANGUAGE_KEYS = 256


@dataclass
class WatchResult:
    traceback: str
    returncode: Optional[int]


class TracebackBlockDetector:
    """Capture full Python traceback blocks from live terminal output."""

    def __init__(self, on_traceback: Callable[[str], None]):
        self.on_traceback = on_traceback
        self._capturing = False
        self._lines: List[str] = []
        self._capture_size = 0

    def feed(self, line: str) -> None:
        line = str(line)
        if line.lstrip().startswith("Traceback (most recent call last):"):
            self._capturing = True
            self._lines = [line]
            self._capture_size = len(line)
            return

        if not self._capturing and line.lstrip().startswith('File "'):
            self._capturing = True
            self._lines = [line]
            self._capture_size = len(line)
            return

        if not self._capturing:
            return

        self._lines.append(line)
        self._capture_size += len(line)
        while self._lines and self._capture_size > MAX_TRACEBACK_CAPTURE_SIZE:
            removed = self._lines.pop(0)
            self._capture_size -= len(removed)
        if self._is_traceback_end(line):
            traceback = "".join(self._lines)
            self._capturing = False
            self._lines = []
            self._capture_size = 0
            self.on_traceback(traceback)

    def flush(self) -> None:
        if self._capturing and self._lines:
            traceback = "".join(self._lines)
            self._capturing = False
            self._lines = []
            self._capture_size = 0
            self.on_traceback(traceback)

    def _is_traceback_end(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if stripped.startswith(("File ", "~", "^")):
            return False
        if stripped.startswith(("raise ", "return ", "print(", "import ", "from ")):
            return False
        return bool(re.match(
            r"[A-Za-z_][A-Za-z0-9_.]*(Error|Exception|Warning|Interrupt|Exit|ImproperlyConfigured|HTTPException|OperationalError|ProgrammingError|ValidationError|TemplateNotFound|TemplateDoesNotExist)(:|$)",
            stripped,
        ))


class TerminalWatcher:
    """Run a command normally while GhostFix watches stdout/stderr live."""

    def __init__(
        self,
        command: str,
        cwd: Optional[str] = None,
        *,
        auto_fix: bool = False,
        verbose: bool = False,
        dry_run: bool = False,
    ):
        self.command = command
        self.cwd = cwd or str(Path.cwd())
        self.auto_fix = auto_fix
        self.verbose = verbose
        self.dry_run = dry_run
        self.analyzer = RootCauseAnalyzer()
        self.validator = PatchValidator()
        self._handled_tracebacks: set[str] = set()
        self._handled_traceback_order: Deque[str] = deque()
        self._duplicate_traceback_counts: dict[str, int] = {}
        self._recent_runtime_lines: Deque[str] = deque(maxlen=MAX_RUNTIME_LOG_LINES)
        self._handled_language_keys: set[str] = set()
        self._handled_language_order: Deque[str] = deque()
        self.runtime_profile = infer_runtime_profile(command=command, cwd=self.cwd)
        self._last_traceback = ""

    def watch(self) -> WatchResult:
        console.print(f"GhostFix watching command:\n{self.command}\n")
        preflight = diagnose_tooling(self.command, cwd=self.cwd)
        if preflight:
            self._last_traceback = preflight.get("message", "")
            self._handle_language_diagnostic(preflight)
            return WatchResult(traceback=self._last_traceback, returncode=1)
        detected: List[str] = []
        pipeline = LogEventPipeline(
            source_type=LogSourceType.SUBPROCESS,
            max_buffer_size=MAX_STREAM_BUFFER_SIZE,
            max_event_size=MAX_STREAM_EVENT_SIZE,
            max_traceback_size=MAX_TRACEBACK_CAPTURE_SIZE,
        )

        process = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        assert process.stdout is not None
        for line in process.stdout:
            self._safe_write(line)
            self._maybe_handle_streaming_language_error(line)
            for event in pipeline.feed(line, stream="stdout"):
                if event.kind == LogEventKind.PYTHON_TRACEBACK:
                    detected.append(event.text)
            self._drain_detected(detected)

        returncode = process.wait()
        process.stdout.close()
        for event in pipeline.flush():
            if event.kind == LogEventKind.PYTHON_TRACEBACK:
                detected.append(event.text)
        self._drain_detected(detected)
        if not self._last_traceback:
            full_output = pipeline.buffered_text()
            extracted = extract_runtime_error(full_output, command=self.command)
            if extracted and extracted.get("kind") == "python_traceback":
                self._last_traceback = extracted["error_block"]
                self._handle_traceback(extracted["error_block"])
                return WatchResult(traceback=self._last_traceback, returncode=returncode)
            diagnostic = self._runtime_diagnostic(extracted, full_output)
            if not diagnostic:
                diagnostic = self._local_llm_diagnostic(full_output)
            if diagnostic:
                self._last_traceback = full_output
                self._handle_language_diagnostic(diagnostic)
        return WatchResult(traceback=self._last_traceback, returncode=returncode)

    def _safe_write(self, text: str) -> None:
        encoding = sys.stdout.encoding or "utf-8"
        sys.stdout.write(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))
        sys.stdout.flush()

    def _drain_detected(self, detected: List[str]) -> None:
        while detected:
            traceback = detected.pop(0)
            key = self._traceback_key(traceback)
            if key in self._handled_tracebacks:
                self._duplicate_traceback_counts[key] = self._duplicate_traceback_counts.get(key, 0) + 1
                if self._duplicate_traceback_counts[key] >= MAX_REPEATED_DUPLICATE_TRACEBACKS:
                    self._duplicate_traceback_counts[key] = MAX_REPEATED_DUPLICATE_TRACEBACKS
                continue
            self._remember_traceback_key(key)
            self._last_traceback = traceback[-MAX_TRACEBACK_CAPTURE_SIZE:]
            self._handle_traceback(self._last_traceback)

    def _remember_traceback_key(self, key: str) -> None:
        self._handled_tracebacks.add(key)
        self._handled_traceback_order.append(key)
        self._duplicate_traceback_counts[key] = 0
        while len(self._handled_traceback_order) > MAX_HANDLED_TRACEBACK_KEYS:
            old_key = self._handled_traceback_order.popleft()
            self._handled_tracebacks.discard(old_key)
            self._duplicate_traceback_counts.pop(old_key, None)

    def _traceback_key(self, traceback: str) -> str:
        normalized = re.sub(r'File ".*?([\\/][^\\/"]+\.py)"', r'File "\1"', traceback)
        normalized = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", normalized)
        normalized = "\n".join(line.rstrip() for line in normalized.splitlines() if line.strip())
        return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()

    def _maybe_handle_streaming_language_error(self, line: str) -> bool:
        self._recent_runtime_lines.append(str(line))
        if not self._looks_like_streaming_runtime_boundary(line):
            return False
        block = "\n".join(self._recent_runtime_lines)
        diagnostic = diagnose_non_python(block, command=self.command, cwd=self.cwd)
        if not diagnostic or diagnostic.get("error_type") == "UnknownError":
            return False
        key = self._language_diagnostic_key(diagnostic)
        if key in self._handled_language_keys:
            return False
        self._remember_language_key(key)
        self._last_traceback = block[-MAX_TRACEBACK_CAPTURE_SIZE:]
        self._handle_language_diagnostic(diagnostic)
        return True

    def _looks_like_streaming_runtime_boundary(self, line: str) -> bool:
        text = str(line or "").strip().lower()
        if not text:
            return False
        if "could not connect to ollama" in text or "ollama_base_url" in text:
            return True
        if "econnrefused" in text or "connection refused" in text:
            return True
        if "fetch failed" in text and self._recent_runtime_buffer_has_error_context():
            return True
        if ("localhost" in text or "127.0.0.1" in text or "::1" in text) and any(
            token in text for token in ("failed to fetch", "fetch failed", "failed to connect", "connect failed", "refused")
        ):
            return True
        if re.search(r"\b(?:get|post|put|patch|delete|options|head)\s+/\S+\s+500\b", text):
            return self._recent_runtime_buffer_has_error_context()
        if "500 internal server error" in text or re.search(r"\bstatus\s*[:=]\s*500\b", text):
            return True
        if ("environment variable" in text or "env var" in text or "process.env." in text) and any(
            token in text for token in ("missing", "required", "not set", "undefined")
        ):
            return True
        return False

    def _recent_runtime_buffer_has_error_context(self) -> bool:
        block = "\n".join(self._recent_runtime_lines).lower()
        return any(
            token in block
            for token in (
                "error:",
                "exception",
                "failed",
                "could not connect",
                "econnrefused",
                "connection refused",
                "process.env.",
                "environment variable",
            )
        )

    def _language_diagnostic_key(self, diagnostic: dict) -> str:
        parts = [
            diagnostic.get("language", ""),
            diagnostic.get("framework", ""),
            diagnostic.get("error_type", ""),
            diagnostic.get("root_cause", ""),
            diagnostic.get("message", ""),
        ]
        normalized = "\n".join(str(part).strip().lower() for part in parts if part)
        normalized = re.sub(r"\b\d+ms\b", "Nms", normalized)
        normalized = re.sub(r":\d{2,5}\b", ":PORT", normalized)
        return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()

    def _remember_language_key(self, key: str) -> None:
        self._handled_language_keys.add(key)
        self._handled_language_order.append(key)
        while len(self._handled_language_order) > MAX_HANDLED_LANGUAGE_KEYS:
            old_key = self._handled_language_order.popleft()
            self._handled_language_keys.discard(old_key)

    def _handle_traceback(self, traceback: str) -> None:
        console.print("\n[error detected]\n", style="bold red", markup=False)
        evidence = self.analyzer.analyze(traceback, cwd=self.cwd, command=self.command)
        parsed = {
            "raw": evidence.raw_traceback,
            "type": evidence.error_type,
            "message": evidence.error_message,
            "file": evidence.file_path,
            "line": evidence.line_number,
        }
        decision = decide_fix(parsed, evidence.code_context)
        if evidence.source in {"framework_rule", "parser"}:
            decision.cause = evidence.likely_root_cause or evidence.root_cause
            decision.fix = evidence.suggested_fix or decision.fix
            decision.source = evidence.source
            decision.confidence = max(decision.confidence, evidence.confidence / 100.0)
        safe_block = self._safe_patch_block(evidence, parsed, decision.to_dict())
        validation = self.validator.validate(safe_block)
        classification = classify_failure(
            root_cause=evidence.root_cause,
            error_type=evidence.error_type,
            patch_available=bool(safe_block and safe_block.get("available")),
            validation_available=validation.ok,
            sensitive_target=bool(evidence.file_path and is_sensitive_target(evidence.file_path)),
            exact_match=bool((safe_block or {}).get("available") and (evidence.exact_symbol_matches or evidence.source in {"parser", "framework_rule"})),
            multi_file=False,
        )
        repo_confidence = compute_confidence(
            validation_success=validation.ok,
            exact_symbol_or_file_match=bool(evidence.exact_symbol_matches or evidence.file_path),
            framework_confidence=evidence.confidence,
            parser_confidence=confidence_percent(decision.confidence),
            stacktrace_quality=90 if evidence.frames else 45,
        )
        if validation.ok and evidence.error_type == "NameError" and evidence.exact_symbol_matches:
            repo_confidence = max(repo_confidence, 96)
        decision.confidence = max(decision.confidence, repo_confidence / 100.0)
        decision.complexity_class = classification
        decision = apply_safety_policy(
            decision,
            patch_available=bool(safe_block and safe_block.get("available")),
            patch_valid=validation.ok,
        )

        auto_fix_available = decision.auto_fix_available and validation.ok
        patch_plan = (safe_block or {}).get("reason") or decision.auto_fix_plan
        incident = make_incident(
            command=self.command,
            file=evidence.file_path or "",
            language="python",
            runtime=evidence.framework or "python",
            error_type=decision.error_type or evidence.error_type,
            cause=decision.cause or evidence.likely_root_cause or evidence.root_cause,
            fix=decision.fix or evidence.suggested_fix,
            confidence=decision.confidence,
            auto_fix_available=auto_fix_available,
            resolved_after_fix=False,
        )

        if not self.verbose:
            decision.auto_fix_available = auto_fix_available
            decision.auto_fix_plan = patch_plan
            if not self.auto_fix:
                decision.auto_fix_available = False
                decision.auto_fix_plan = "Watch mode diagnosis only. Re-run with --fix to allow deterministic safe Python auto-fix."
                decision.safety_policy_reason = decision.auto_fix_plan
            show_output({
                "status": decision.status,
                "decision": decision,
                "error": traceback,
                "context": evidence.code_context,
                "patch": safe_block.get("patch") if safe_block else "",
                "structured_patch_plan": structured_plan_from_patch_block(
                    safe_block,
                    classification=classification,
                    explanation=decision.cause or evidence.likely_root_cause or evidence.root_cause,
                    confidence=confidence_percent(decision.confidence),
                    command=self.command,
                ).to_dict(),
                "verbose": False,
            })
        else:
            self._print_verbose_python_panel(evidence, decision, safe_block, validation, auto_fix_available, patch_plan)

        if not self.auto_fix:
            record_incident(incident, root=Path(self.cwd))
            record_v07_metric(Path(self.cwd), "unsafe_block_rate" if classification == "unsafe_blocked" else "unresolved_rate")
            return

        if not auto_fix_available:
            if safe_block and safe_block.get("patch"):
                record_fix_audit(
                    target_file=evidence.file_path or "",
                    patch=safe_block.get("patch") or "",
                    validator_result=decision.safety_policy_reason or validation.reason or "Auto-fix blocked by safety policy.",
                    rollback_available=False,
                    user_confirmed=False,
                    root=Path(self.cwd),
                )
            record_incident(incident, root=Path(self.cwd))
            record_v07_metric(Path(self.cwd), "unsafe_block_rate" if classification == "unsafe_blocked" else "unresolved_rate")
            return

        if self.dry_run:
            print("DRY_RUN: enabled")
            print("No code will be modified")
            record_fix_audit(
                target_file=evidence.file_path or "",
                patch=(safe_block or {}).get("patch") or "",
                validator_result="dry-run; patch not applied",
                rollback_available=False,
                user_confirmed=False,
                root=Path(self.cwd),
            )
            record_incident(incident, root=Path(self.cwd))
            return

        if not Confirm.ask("Apply fix?", default=False):
            console.print("Patch not applied.")
            record_fix_audit(
                target_file=evidence.file_path or "",
                patch=(safe_block or {}).get("patch") or "",
                validator_result="User declined",
                rollback_available=False,
                user_confirmed=False,
                root=Path(self.cwd),
            )
            record_incident(incident, root=Path(self.cwd))
            log_decision_feedback(
                parsed_error=parsed,
                context=evidence.code_context,
                decision=decision,
                accepted=False,
                auto_fix_attempted=False,
                success_after_fix=False,
            )
            return

        result = self.validator.apply_with_backup_and_compile(safe_block)
        record_fix_audit(
            target_file=evidence.file_path or "",
            backup_path=result.get("backup") or "",
            patch=(safe_block or {}).get("patch") or "",
            validator_result=result.get("reason") or "",
            rollback_available=bool((result.get("rollback_metadata") or {}).get("backup")),
            user_confirmed=True,
            root=Path(self.cwd),
        )
        if not result.get("applied"):
            console.print(f"Patch not applied: {result.get('reason')}", style="yellow")
            incident.rollback_metadata = result.get("rollback_metadata") or {}
            record_incident(incident, root=Path(self.cwd))
            log_decision_feedback(
                parsed_error=parsed,
                context=evidence.code_context,
                decision=decision,
                accepted=True,
                auto_fix_attempted=True,
                success_after_fix=False,
            )
            return

        console.print(f"Backup created: {result.get('backup')}")
        print("Rollback is available.")
        console.print("Rerunning original command...\n")
        rerun = rerun_command(self.command, cwd=self.cwd)
        if rerun.stdout:
            console.print(rerun.stdout)
        if rerun.stderr:
            console.print(rerun.stderr, style="red")
        if rerun.success:
            console.print("Verification: original command now exits successfully.", style="bold green")
            record_v07_metric(Path(self.cwd), "fix_success_rate")
            record_v07_metric(Path(self.cwd), "rerun_success_rate")
            if classification == "deterministic_safe":
                record_v07_metric(Path(self.cwd), "deterministic_solve_rate")
        else:
            console.print(f"Verification failed: command exited with {rerun.returncode}.", style="bold red")
            record_v07_metric(Path(self.cwd), "unresolved_rate")
        incident.resolved_after_fix = rerun.success
        incident.rollback_metadata = result.get("rollback_metadata") or {}
        record_incident(incident, root=Path(self.cwd))

        log_decision_feedback(
            parsed_error=parsed,
            context=evidence.code_context,
            decision=decision,
            accepted=True,
            auto_fix_attempted=True,
            success_after_fix=rerun.success,
        )

    def _print_verbose_python_panel(self, evidence, decision, safe_block, validation, auto_fix_available: bool, patch_plan: str) -> None:
        console.print(f"ERROR_TYPE:\n{decision.error_type or evidence.error_type}\n")
        console.print(f"FRAMEWORK:\n{evidence.framework or 'python'}\n")
        console.print(f"FAILING_FILE:\n{evidence.file_path or ''}\n")
        console.print(f"FAILING_LINE:\n{evidence.line_number or ''}\n")
        console.print(f"FAILING_CODE:\n{evidence.failing_line or ''}\n")
        console.print(f"ROOT_CAUSE:\n{decision.cause}\n")
        console.print(f"LIKELY_ROOT_CAUSE:\n{evidence.likely_root_cause or evidence.root_cause}\n")
        console.print(f"EVIDENCE:\n{self._format_evidence(evidence.evidence)}\n")
        console.print(f"FIX:\n{decision.fix}\n")
        console.print(f"SUGGESTED_FIX:\n{evidence.suggested_fix or decision.fix}\n")
        console.print(f"SOURCE:\n{decision.source}\n")
        console.print(f"BRAIN_VERSION:\n{decision.brain_version}\n")
        console.print(f"BRAIN_FLAG_ACTIVE:\n{decision.brain_flag_active}\n")
        console.print(f"BRAIN_TYPE:\n{decision.brain_type}\n")
        console.print(f"BRAIN_FIX_TEMPLATE:\n{decision.brain_fix_template}\n")
        console.print(f"FIX_TEMPLATE:\n{decision.brain_fix_template}\n")
        console.print(f"BRAIN_CONFIDENCE:\n{confidence_percent(decision.brain_confidence)}%\n")
        console.print(f"BRAIN_IGNORED_REASON:\n{decision.brain_ignored_reason}\n")
        console.print(f"CONFIDENCE:\n{confidence_percent(decision.confidence)}%\n")
        console.print(f"COMPLEXITY_CLASS:\n{decision.complexity_class}\n")
        console.print(f"AUTO_FIX_SAFETY:\n{decision.auto_fix_safety}\n")
        console.print(f"GUARD_APPLIED:\n{'yes' if decision.guard_applied else 'no'}\n")
        console.print(f"AUTO_FIX_AVAILABLE:\n{'yes' if auto_fix_available else 'no'}\n")
        if not auto_fix_available:
            console.print(f"AUTO_FIX_BLOCK_REASON:\n{decision.safety_policy_reason}\n")
        console.print(f"SAFETY_REASON:\n{decision.safety_policy_reason}\n")
        console.print(f"PATCH_PLAN:\n{patch_plan}\n")
        console.print(f"FAILURE_CLASSIFICATION:\n{decision.complexity_class or ''}\n")
        if safe_block and safe_block.get("patch"):
            console.print(safe_block["patch"])
        if not validation.ok:
            console.print(f"SAFETY:\n{validation.reason}\n")

    def _handle_language_diagnostic(self, diagnostic: dict) -> None:
        console.print("\n[error detected]\n", style="bold red", markup=False)
        next_step = diagnostic.get("suggested_fix", "") or "Review the runtime log and fix the startup error."
        auto_fix = bool(diagnostic.get("auto_fix_available", False))
        print("STATUS: error")
        print(f"ERROR: {diagnostic.get('error_type', '')}")
        print(f"LANGUAGE: {diagnostic.get('language', 'unknown')}")
        print(f"FRAMEWORK: {diagnostic.get('framework', 'unknown')}")
        print(f"RUNTIME: {diagnostic.get('runtime') or self.runtime_profile.runtime}")
        print(f"FAILING_FILE: {diagnostic.get('file', '')}")
        print(f"EXACT_FILE: {diagnostic.get('file', '')}")
        print(f"FAILING_LINE: {diagnostic.get('line') or ''}")
        print(f"ROOT_CAUSE: {diagnostic.get('likely_root_cause') or diagnostic.get('root_cause', '')}")
        evidence = diagnostic.get("evidence") or []
        if evidence:
            print(f"EVIDENCE: {len(evidence)}")
            for item in evidence[:4]:
                print(f"- {item}")
        route = diagnostic.get("route") or ""
        if route:
            print(f"ROUTE: {route}")
        print(f"SUGGESTED_FIX: {next_step}")
        print(f"NEXT_STEP: {next_step}")
        print(f"Next step: {next_step}")
        print(f"AUTO_FIX: {'yes' if auto_fix else 'no'}")
        print(f"CONFIDENCE: {diagnostic.get('confidence', 0)}%")
        print(f"FAILURE_CLASSIFICATION: {diagnostic.get('failure_classification') or 'suggestion_only'}")
        print(f"AUTO_FIX_AVAILABLE={'yes' if auto_fix else 'no'}")
        block_reason = diagnostic.get("why_auto_fix_blocked") or diagnostic.get("safety_reason") or ""
        if not auto_fix:
            print(f"WHY_AUTO_FIX_BLOCKED: {block_reason}")
        print(f"Auto-fix available: {'yes' if auto_fix else 'no'}")
        print("ROLLBACK_AVAILABLE: no")
        print("Rollback available: no")
        patch_block = diagnostic.get("patch_block") or {}
        patch_preview = diagnostic.get("patch_preview") or patch_block.get("patch") or ""
        if patch_preview:
            print("PATCH_PREVIEW:")
            print(patch_preview)
        plan = diagnostic.get("structured_patch_plan") or {}
        if plan:
            print(f"VALIDATION_RESULT: {'pending real apply' if auto_fix else diagnostic.get('why_auto_fix_blocked', '')}")
            print("APPLY_FIX? y/n")
        rollback_metadata = {}
        if auto_fix:
            rollback_metadata = self._maybe_apply_language_patch(diagnostic, patch_block, patch_preview)
        else:
            print("No code was changed")
        record_incident(
            make_incident(
                command=self.command,
                file=diagnostic.get("file", ""),
                language=diagnostic.get("language", "unknown"),
                runtime=diagnostic.get("framework") or diagnostic.get("root_cause") or "unknown",
                error_type=diagnostic.get("error_type", ""),
                cause=diagnostic.get("likely_root_cause") or diagnostic.get("root_cause", ""),
                fix=diagnostic.get("suggested_fix", ""),
                confidence=diagnostic.get("confidence", 0),
                auto_fix_available=diagnostic.get("auto_fix_available", False),
                resolved_after_fix=False,
                rollback_metadata=rollback_metadata,
            ),
            root=Path(self.cwd),
        )
        content = f"""LANGUAGE:
{diagnostic['language']}

FRAMEWORK:
{diagnostic.get('framework') or 'unknown'}

RUNTIME:
{diagnostic.get('runtime') or self.runtime_profile.runtime}

ERROR_TYPE:
{diagnostic['error_type']}

CAUSE:
{diagnostic['likely_root_cause']}

FIX:
{diagnostic['suggested_fix']}

EVIDENCE:
{self._format_evidence(diagnostic.get('evidence') or [])}

ROUTE:
{diagnostic.get('route') or ''}

CONFIDENCE:
{diagnostic['confidence']}%

AUTO_FIX_AVAILABLE:
{'yes' if diagnostic.get('auto_fix_available') else 'no'}
"""
        if self.verbose:
            content += f"""
FRAMEWORK:
{diagnostic['framework']}

FAILING_FILE:
{diagnostic['file']}

FAILING_LINE:
{diagnostic['line'] or ''}

ROOT_CAUSE:
{diagnostic['root_cause']}

SOURCE:
{diagnostic['source']}

SAFETY_REASON:
{diagnostic['safety_reason']}
"""
        console.print(Panel(content, title="GhostFix Diagnosis", border_style="cyan"))

    def _maybe_apply_language_patch(self, diagnostic: dict, patch_block: dict, patch_preview: str) -> dict:
        if not patch_block or not patch_block.get("available"):
            print(f"WHY_AUTO_FIX_BLOCKED: {diagnostic.get('why_auto_fix_blocked') or diagnostic.get('safety_reason')}")
            print("No code was changed")
            return {}
        validation = self.validator.validate(patch_block)
        if not validation.ok:
            print(f"WHY_AUTO_FIX_BLOCKED: {validation.reason}")
            print("No code was changed")
            record_fix_audit(
                target_file=patch_block.get("file_path", ""),
                patch=patch_preview,
                validator_result=validation.reason,
                rollback_available=False,
                user_confirmed=False,
                root=Path(self.cwd),
            )
            return {}
        if self.dry_run:
            print("DRY_RUN: enabled")
            print("No code will be modified")
            record_fix_audit(
                target_file=patch_block.get("file_path", ""),
                patch=patch_preview,
                validator_result="dry-run; patch not applied",
                rollback_available=False,
                user_confirmed=False,
                root=Path(self.cwd),
            )
            return {}
        if not Confirm.ask("Apply fix?", default=False):
            print("No code was changed")
            record_fix_audit(
                target_file=patch_block.get("file_path", ""),
                patch=patch_preview,
                validator_result="User declined",
                rollback_available=False,
                user_confirmed=False,
                root=Path(self.cwd),
            )
            return {}
        result = self.validator.apply_with_backup_and_compile(patch_block)
        record_fix_audit(
            target_file=patch_block.get("file_path", ""),
            backup_path=result.get("backup") or "",
            patch=patch_preview,
            validator_result=result.get("reason") or "",
            rollback_available=bool((result.get("rollback_metadata") or {}).get("backup")),
            user_confirmed=True,
            root=Path(self.cwd),
        )
        if not result.get("applied"):
            print(f"WHY_AUTO_FIX_BLOCKED: {result.get('reason')}")
            print("No code was changed")
            return result.get("rollback_metadata") or {}
        print(f"Backup created: {result.get('backup')}")
        print("Rollback is available.")
        return result.get("rollback_metadata") or {}

    def _runtime_diagnostic(self, extracted: Optional[dict], full_output: str) -> Optional[dict]:
        tooling = diagnose_tooling(self.command, cwd=self.cwd, output=full_output)
        # Command-output evidence wins over static tooling guesses
        if tooling and not extracted:
            return tooling
        if extracted and extracted.get("kind") in {
            "port_in_use",
            "missing_env_var",
            "command_not_found",
            "npm_package_json_missing",
        }:
            return {
                "language": extracted.get("language") or "unknown",
                "error_type": extracted["type"],
                "message": extracted["message"],
                "file": "",
                "line": 0,
                "framework": extracted.get("framework") or "unknown",
                "root_cause": extracted.get("kind") or "runtime_error",
                "likely_root_cause": _runtime_root_cause(extracted),
                "suggested_fix": _suggest_runtime_fix(extracted),
                "confidence": 92,
                "source": "runtime_parser",
                "auto_fix_available": False,
                "safety_reason": "Watch mode diagnosis only; command/runtime issues are not auto-fixed.",
            }
        if extracted and extracted.get("language") == "python":
            return {
                "language": "python",
                "error_type": extracted["type"],
                "message": extracted["message"],
                "file": "",
                "line": 0,
                "framework": extracted.get("framework") or "python",
                "root_cause": extracted.get("kind") or "python_runtime_error",
                "likely_root_cause": extracted["message"],
                "suggested_fix": _suggest_runtime_fix(extracted),
                "confidence": 84,
                "source": "runtime_parser",
                "auto_fix_available": False,
                "safety_reason": "No deterministic Python patch was produced from this log-only error.",
            }
        return diagnose_non_python(full_output, command=self.command, cwd=self.cwd)

    def _local_llm_diagnostic(self, output: str) -> Optional[dict]:
        try:
            from core.local_llm import diagnose_terminal_output

            language = detect_language(command=self.command, output=output)
            return diagnose_terminal_output(
                output,
                command=self.command,
                cwd=self.cwd,
                language=language,
                framework="unknown",
            )
        except Exception:
            return None

    def _safe_patch_block(self, evidence, parsed: dict, decision: dict):
        if not evidence.file_path:
            return None
        plan = build_patch_plan(evidence.file_path, parsed, decision)
        if not plan.available:
            repo_plan = self._missing_python_import_patch(evidence)
            if repo_plan:
                return repo_plan
            return {"available": False, "reason": plan.reason}
        return {
            "available": True,
            "reason": plan.reason,
            "file_path": evidence.file_path,
            "start_line": plan.start_line,
            "end_line": plan.end_line,
            "replacement": plan.replacement,
            "patch": plan.preview,
        }

    def _missing_python_import_patch(self, evidence) -> dict | None:
        if evidence.error_type != "NameError" or not evidence.missing_name or len(evidence.exact_symbol_matches) != 1:
            return None
        target_rel = evidence.exact_symbol_matches[0]
        target_path = Path(evidence.project_context.root) / target_rel if evidence.project_context else Path(target_rel)
        file_path = Path(evidence.file_path)
        if is_sensitive_target(file_path):
            return None
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError:
            return None
        module = self._python_module_from_path(target_path, Path(evidence.project_context.root) if evidence.project_context else Path(self.cwd))
        if not module:
            return None
        import_line = f"from {module} import {evidence.missing_name}\n"
        if any(line.strip() == import_line.strip() for line in lines):
            return None
        insert_at = self._python_import_insert_line(lines)
        new_lines = lines[:]
        new_lines[insert_at:insert_at] = [import_line]
        return {
            "available": True,
            "reason": f"Safe missing-import patch: exact local symbol `{evidence.missing_name}` found in `{target_rel}`.",
            "file_path": str(file_path),
            "start_line": insert_at + 1,
            "end_line": insert_at + 1,
            "replacement": import_line + (lines[insert_at] if insert_at < len(lines) else ""),
            "patch": "".join(difflib.unified_diff(
                [line if line.endswith("\n") else f"{line}\n" for line in lines],
                [line if line.endswith("\n") else f"{line}\n" for line in new_lines],
                fromfile=str(file_path),
                tofile=str(file_path),
                lineterm="\n",
            )),
            "validation": "ast.parse + compile + sandbox validation",
        }

    def _python_import_insert_line(self, lines: list[str]) -> int:
        index = 0
        if lines and lines[0].startswith("#!"):
            index = 1
        while index < len(lines) and (lines[index].strip().startswith("#") or not lines[index].strip()):
            index += 1
        if index < len(lines) and re.match(r"^[rubfRUBF]*['\"]{3}", lines[index].lstrip()):
            quote = lines[index].lstrip()[:3]
            index += 1
            while index < len(lines) and quote not in lines[index]:
                index += 1
            index += 1
        while index < len(lines) and (lines[index].startswith("import ") or lines[index].startswith("from ")):
            index += 1
        return index

    def _python_module_from_path(self, path: Path, root: Path) -> str:
        try:
            rel = path.resolve().relative_to(root.resolve())
        except ValueError:
            return ""
        parts = list(rel.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts)

    def _format_evidence(self, evidence: List[str]) -> str:
        if not evidence:
            return "No local evidence available."
        return "\n".join(f"- {item}" for item in evidence)


def _suggest_runtime_fix(extracted: dict) -> str:
    kind = extracted.get("kind")
    if kind == "port_in_use":
        return "Stop the process using that port or run the server on a different port."
    if kind == "missing_env_var":
        return "Set the missing environment variable before starting the server, or add explicit config validation."
    if kind == "command_not_found":
        return "Install uvicorn in the active environment or run python -m uvicorn if it is available."
    if kind == "npm_package_json_missing":
        return "cd into the project folder or create package.json with npm init."
    return "Review the server log and fix the reported startup condition before rerunning."


def _runtime_root_cause(extracted: dict) -> str:
    kind = extracted.get("kind")
    if kind == "port_in_use":
        return "The configured server port is already in use by another process."
    if kind == "missing_env_var":
        return "A required environment variable is missing from the server process."
    if kind == "command_not_found":
        return "uvicorn is not installed or not on PATH."
    if kind == "npm_package_json_missing":
        return "npm was run outside a Node project or package.json is missing."
    return extracted.get("message") or "The runtime command failed before the app could start."


def watch_command(
    command: str,
    cwd: Optional[str] = None,
    *,
    auto_fix: bool = False,
    verbose: bool = False,
    dry_run: bool = False,
) -> WatchResult:
    return TerminalWatcher(command, cwd=cwd, auto_fix=auto_fix, verbose=verbose, dry_run=dry_run).watch()
