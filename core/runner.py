import subprocess
from pathlib import Path

from rich.prompt import Confirm

from core.autofix import apply_patch_plan, build_patch_plan
from core.context import extract_context
from core.decision_engine import apply_safety_policy, decide_fix
from core.fix_audit import record_fix_audit
from core.formatter import show_output
from core.incidents import make_incident, record_incident
from core.logger import log_error
from core.parser import parse_error
from ml.feedback_logger import log_decision_feedback


def run_command(
    file_path: str,
    auto_fix: bool = False,
    max_loops: int = 3,
    verbose: bool = False,
    auto_approve: bool = False,
    dry_run: bool = False,
):
    pending_feedback = None
    pending_incident = None

    for attempt in range(max_loops):
        process = subprocess.Popen(
            ["python", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        stdout, stderr = process.communicate()
        if stdout:
            print(stdout)

        parsed = parse_error(stderr)
        if not parsed:
            if pending_feedback:
                log_decision_feedback(**pending_feedback, success_after_fix=True)
            if pending_incident:
                pending_incident.resolved_after_fix = True
                record_incident(pending_incident)
            show_output({"status": "success", "verbose": verbose})
            return

        if pending_feedback:
            log_decision_feedback(**pending_feedback, success_after_fix=False)
            pending_feedback = None
        if pending_incident:
            pending_incident.resolved_after_fix = False
            record_incident(pending_incident)
            pending_incident = None

        parsed["verbose"] = verbose
        context = extract_context(file_path, stderr)
        decision = decide_fix(parsed, context)
        patch_plan = build_patch_plan(file_path, parsed, decision.to_dict())
        patch_preview = patch_plan.preview if patch_plan.available else ""
        decision.patch = patch_preview
        decision = apply_safety_policy(
            decision,
            patch_available=patch_plan.available,
            patch_valid=patch_plan.available,
            fix_kind=patch_plan.fix_kind,
            validation=patch_plan.validation,
            changed_line_count=patch_plan.changed_line_count,
            deterministic_validator_result=patch_plan.deterministic_validator_result,
            compile_validation_result=patch_plan.compile_validation_result,
        )

        autofix_result = None
        if auto_fix:
            can_apply = patch_plan.available and decision.auto_fix_available
            if dry_run:
                autofix_result = {"applied": False, "reason": "dry-run"}
                if patch_plan.available:
                    record_fix_audit(
                        target_file=file_path,
                        patch=patch_preview,
                        validator_result="dry-run; patch not applied",
                        rollback_available=False,
                        user_confirmed=False,
                        root=Path.cwd(),
                    )
                show_output({
                    "status": decision.status,
                    "decision": decision,
                    "error": stderr,
                    "context": context,
                    "patch": patch_preview,
                    "autofix": autofix_result,
                    "verbose": verbose,
                })
            elif can_apply and not auto_approve:
                autofix_result = {"applied": False, "reason": "waiting for confirmation"}
                show_output({
                    "status": decision.status,
                    "decision": decision,
                    "error": stderr,
                    "context": context,
                    "patch": patch_preview,
                    "autofix": autofix_result,
                    "verbose": verbose,
                })

            user_confirmed = False if dry_run else bool(can_apply and (auto_approve or Confirm.ask("Apply fix?", default=False)))
            if not dry_run and user_confirmed:
                autofix_result = apply_patch_plan(file_path, patch_plan)
                record_fix_audit(
                    target_file=file_path,
                    backup_path=autofix_result.get("backup") or "",
                    patch=patch_preview,
                    validator_result=autofix_result.get("reason") or autofix_result.get("message") or "",
                    rollback_available=bool((autofix_result.get("rollback_metadata") or {}).get("backup")),
                    user_confirmed=True,
                    root=Path.cwd(),
                )
                if autofix_result.get("applied"):
                    print("Rollback is available.")
                    pending_feedback = {
                        "parsed_error": parsed,
                        "context": context,
                        "decision": decision,
                        "accepted": True,
                        "auto_fix_attempted": True,
                    }
                    pending_incident = make_incident(
                        command=f"python {file_path}",
                        file=file_path,
                        language="python",
                        runtime="python",
                        error_type=parsed.get("type", ""),
                        cause=decision.cause,
                        fix=decision.fix,
                        confidence=decision.confidence,
                        auto_fix_available=True,
                        resolved_after_fix=False,
                        rollback_metadata=autofix_result.get("rollback_metadata") or {},
                    )
                else:
                    log_decision_feedback(
                        parsed_error=parsed,
                        context=context,
                        decision=decision,
                        accepted=True,
                        auto_fix_attempted=True,
                        success_after_fix=False,
                    )
            elif not dry_run:
                if not autofix_result or autofix_result.get("reason") != "waiting for confirmation":
                    autofix_result = {
                        "applied": False,
                        "reason": decision.safety_policy_reason or (patch_plan.reason if not patch_plan.available else "User declined"),
                    }
                if patch_plan.available:
                    record_fix_audit(
                        target_file=file_path,
                        patch=patch_preview,
                        validator_result=autofix_result.get("reason") or "not applied",
                        rollback_available=False,
                        user_confirmed=False,
                        root=Path.cwd(),
                    )
                if patch_plan.available:
                    log_decision_feedback(
                        parsed_error=parsed,
                        context=context,
                        decision=decision,
                        accepted=False,
                        auto_fix_attempted=False,
                        success_after_fix=False,
                    )

        log_error(parsed, decision.to_dict(), context)
        if not pending_incident:
            record_incident(
                make_incident(
                    command=f"python {file_path}",
                    file=file_path,
                    language="python",
                    runtime="python",
                    error_type=parsed.get("type", ""),
                    cause=decision.cause,
                    fix=decision.fix,
                    confidence=decision.confidence,
                    auto_fix_available=decision.auto_fix_available,
                    resolved_after_fix=False,
                )
            )

        if not (auto_fix and (dry_run or (patch_plan.available and decision.auto_fix_available and not auto_approve))):
            show_output({
                "status": decision.status,
                "decision": decision,
                "error": stderr,
                "context": context,
                "patch": patch_preview,
                "autofix": autofix_result,
                "verbose": verbose,
            })

        if not auto_fix or not autofix_result or not autofix_result.get("applied"):
            break

        print("\nRe-running after auto-fix...\n")

    if pending_feedback:
        log_decision_feedback(**pending_feedback, success_after_fix=False)
    if pending_incident:
        pending_incident.resolved_after_fix = False
        record_incident(pending_incident)
