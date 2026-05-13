from __future__ import annotations

import subprocess
import sys
import hashlib
import re
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
from core.root_cause_analyzer import RootCauseAnalyzer
from ml.feedback_logger import log_decision_feedback


console = Console()
MAX_TRACEBACK_CAPTURE_SIZE = 64_000
MAX_HANDLED_TRACEBACK_KEYS = 256
MAX_REPEATED_DUPLICATE_TRACEBACKS = 25
MAX_STREAM_BUFFER_SIZE = 128_000
MAX_STREAM_EVENT_SIZE = 32_000


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
        self._last_traceback = ""

    def watch(self) -> WatchResult:
        console.print(f"GhostFix watching command:\n{self.command}\n")
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
                "verbose": False,
            })
        else:
            self._print_verbose_python_panel(evidence, decision, safe_block, validation, auto_fix_available, patch_plan)

        if not self.auto_fix:
            record_incident(incident, root=Path(self.cwd))
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
        else:
            console.print(f"Verification failed: command exited with {rerun.returncode}.", style="bold red")
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
        print(f"ROOT_CAUSE: {diagnostic.get('likely_root_cause') or diagnostic.get('root_cause', '')}")
        print(f"NEXT_STEP: {next_step}")
        print(f"Next step: {next_step}")
        print(f"AUTO_FIX: {'yes' if auto_fix else 'no'}")
        print(f"Auto-fix available: {'yes' if auto_fix else 'no'}")
        print("ROLLBACK_AVAILABLE: no")
        print("Rollback available: no")
        if not auto_fix:
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
            ),
            root=Path(self.cwd),
        )
        content = f"""LANGUAGE:
{diagnostic['language']}

ERROR_TYPE:
{diagnostic['error_type']}

CAUSE:
{diagnostic['likely_root_cause']}

FIX:
{diagnostic['suggested_fix']}

CONFIDENCE:
{diagnostic['confidence']}%

AUTO_FIX_AVAILABLE:
no
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
        console.print(Panel(content, title="GhostFix Brain", border_style="cyan"))

    def _runtime_diagnostic(self, extracted: Optional[dict], full_output: str) -> Optional[dict]:
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
