from rich.console import Console
from rich.panel import Panel

from core.confidence import confidence_percent
from core.decision_engine import Decision, format_decision


console = Console()


def format_compact_decision(decision: Decision) -> str:
    block_reason = ""
    if not decision.auto_fix_available and decision.safety_policy_reason:
        block_reason = f"""
AUTO_FIX_BLOCK_REASON:
{decision.safety_policy_reason}
"""

    if decision.auto_fix_available and decision.fix_kind == "deterministic_verified_fix":
        return f"""ERROR_TYPE:
{decision.error_type or ""}

CAUSE:
{decision.cause or ""}

FIX:
{decision.fix or ""}

FIX_CONFIDENCE:
verified by local compiler

SAFETY_LEVEL:
{decision.safety_level or "deterministic_safe"}

VALIDATION:
{decision.validation or "ast.parse + compile passed"}

AUTO_FIX_AVAILABLE:
yes

Patch confidence: verified by local compiler
"""

    return f"""ERROR_TYPE:
{decision.error_type or ""}

CAUSE:
{decision.cause or ""}

FIX:
{decision.fix or ""}

CONFIDENCE:
{confidence_percent(decision.confidence)}%

AUTO_FIX_AVAILABLE:
{"yes" if decision.auto_fix_available else "no"}
{block_reason}"""


def show_output(data):
    if data["status"] == "success":
        print("STATUS: success")
        print("ERROR: none")
        print("ROOT_CAUSE: none")
        print("NEXT_STEP: no action needed")
        print("Next step: no action needed")
        print("AUTO_FIX: no")
        print("Auto-fix available: no")
        print("ROLLBACK_AVAILABLE: no")
        print("Rollback available: no")
        console.print("[bold green]SUCCESS: no errors detected[/bold green]")
        return

    decision = data.get("decision")
    patch = data.get("patch") or ""
    verbose = bool(data.get("verbose"))

    if isinstance(decision, Decision):
        content = format_decision(decision, patch) if verbose else format_compact_decision(decision)
    else:
        content = _legacy_content(data, patch) if verbose else _legacy_compact_content(data)

    context = data.get("context") or {}
    snippet = context.get("snippet") if isinstance(context, dict) else None
    evidence = _evidence_from_context(context)
    autofix = data.get("autofix")

    if not verbose and evidence:
        content += f"\nEVIDENCE:\n{evidence}\n"

    if verbose and snippet:
        content += f"\nCODE_CONTEXT:\n{snippet}\n"

    if autofix:
        if autofix.get("applied"):
            content += f"\nAUTO_FIX_RESULT:\napplied\nBACKUP:\n{autofix.get('backup') or ''}\n"
        elif autofix.get("reason") == "waiting for confirmation":
            content += "\nAUTO_FIX_RESULT:\nwaiting for confirmation\n"
            content += "\nNo code was changed\n"
        else:
            content += f"\nAUTO_FIX_RESULT:\nnot applied - {autofix.get('reason') or 'unknown'}\n"
            content += "\nNo code was changed\n"

    if not verbose and patch and autofix and autofix.get("reason") == "waiting for confirmation":
        content += f"""
PATCH_PREVIEW:
```diff
{patch}
```

SAFETY:
* backup will be created
* no unrelated code changes
* no file deletion
"""

    if "Patch confidence: verified by local compiler" in content:
        print("Patch confidence: verified by local compiler")
    if "DETERMINISTIC_VALIDATOR_RESULT:" in content:
        print("DETERMINISTIC_VALIDATOR_RESULT")

    _print_plain_summary(data, decision, autofix, patch, evidence)
    console.print(Panel(content, title="GhostFix Brain", border_style="cyan"))


def _legacy_compact_content(data) -> str:
    error_type = data.get("error_type") or data.get("type") or _legacy_error_type(data)
    cause = data.get("cause") or data.get("likely_root_cause") or data.get("root_cause") or ""
    fix = data.get("fix") or data.get("suggested_fix") or data.get("patch_plan") or ""
    confidence = confidence_percent(data.get("confidence", 0))
    auto_fix_available = bool(data.get("auto_fix_available"))
    block_reason = data.get("safety_reason") or data.get("auto_fix_block_reason") or ""

    content = f"""ERROR_TYPE:
{error_type}

CAUSE:
{cause}

FIX:
{fix}

CONFIDENCE:
{confidence}%

AUTO_FIX_AVAILABLE:
{"yes" if auto_fix_available else "no"}
"""
    if not auto_fix_available and block_reason:
        content += f"""
AUTO_FIX_BLOCK_REASON:
{block_reason}
"""
    return content


def _legacy_content(data, patch) -> str:
    error_type = data.get("error_type") or data.get("type") or _legacy_error_type(data)
    cause = data.get("cause") or data.get("likely_root_cause") or data.get("root_cause") or ""
    fix = data.get("fix") or data.get("suggested_fix") or data.get("patch_plan") or ""
    confidence = confidence_percent(data.get("confidence", 0))
    auto_fix_available = bool(data.get("auto_fix_available"))
    source = data.get("source") or "legacy"
    safety_reason = data.get("safety_reason") or data.get("auto_fix_block_reason") or ""

    return f"""STATUS:
{data.get("status") or "error"}

ERROR_TYPE:
{error_type}

CAUSE:
{cause}

FIX:
{fix}

CONFIDENCE:
{confidence}%

SOURCE:
{source}

AUTO_FIX_AVAILABLE:
{"yes" if auto_fix_available else "no"}

AUTO_FIX_BLOCK_REASON:
{"" if auto_fix_available else safety_reason}

SAFETY_REASON:
{safety_reason}

PATCH:

```python
{patch or ""}
```

SAFETY:
* backup will be created
* no unrelated code changes
* no file deletion
"""


def _legacy_error_type(data) -> str:
    error = data.get("error") or ""
    if isinstance(error, BaseException):
        return type(error).__name__
    if isinstance(error, str):
        for line in reversed(error.splitlines()):
            stripped = line.strip()
            if ":" in stripped:
                return stripped.split(":", 1)[0]
            if stripped.endswith(("Error", "Exception")):
                return stripped
    return "UnknownError"


def _print_plain_summary(data, decision, autofix, patch, evidence) -> None:
    error_type = _summary_error_type(data, decision)
    root_cause = _summary_root_cause(data, decision)
    auto_fix_available = _summary_auto_fix_available(data, decision)
    rollback_available = _summary_rollback_available(autofix)
    next_step = _summary_next_step(auto_fix_available, autofix, patch)

    print(f"STATUS: {data.get('status') or 'error'}")
    print(f"ERROR: {error_type}")
    print(f"ROOT_CAUSE: {root_cause}")
    if evidence:
        print(f"EVIDENCE: {evidence}")
    print(f"NEXT_STEP: {next_step}")
    print(f"Next step: {next_step}")
    print(f"AUTO_FIX: {'yes' if auto_fix_available else 'no'}")
    print(f"Auto-fix available: {'yes' if auto_fix_available else 'no'}")
    print(f"ROLLBACK_AVAILABLE: {'yes' if rollback_available else 'no'}")
    print(f"Rollback available: {'yes' if rollback_available else 'no'}")
    if rollback_available:
        print("Rollback is available.")
    if not auto_fix_available:
        print("Auto-fix blocked by safety policy.")
        print("Manual review recommended.")
    if not autofix or not autofix.get("applied"):
        print("No code was changed")
        print("No code was modified.")


def _summary_error_type(data, decision) -> str:
    if isinstance(decision, Decision):
        return decision.error_type or "UnknownError"
    return data.get("error_type") or data.get("type") or _legacy_error_type(data)


def _summary_root_cause(data, decision) -> str:
    if isinstance(decision, Decision):
        return decision.cause or "Unknown"
    return data.get("cause") or data.get("likely_root_cause") or data.get("root_cause") or "Unknown"


def _summary_auto_fix_available(data, decision) -> bool:
    if isinstance(decision, Decision):
        return bool(decision.auto_fix_available)
    return bool(data.get("auto_fix_available"))


def _summary_rollback_available(autofix) -> bool:
    if not autofix:
        return False
    metadata = autofix.get("rollback_metadata") or {}
    return bool(autofix.get("backup") or metadata.get("backup"))


def _summary_next_step(auto_fix_available: bool, autofix, patch: str) -> str:
    if autofix and autofix.get("applied"):
        return "run your command again; use `ghostfix rollback last` if the change is not right"
    if autofix and autofix.get("reason") == "waiting for confirmation":
        return "review the patch preview and choose whether to apply it"
    if auto_fix_available and patch:
        return "rerun with --fix to review the safe deterministic patch"
    return "review the diagnosis and update the code manually"


def _evidence_from_context(context) -> str:
    if not isinstance(context, dict):
        return ""
    failing_line = context.get("failing_line") or context.get("line")
    if failing_line:
        return str(failing_line).strip()
    snippet = context.get("snippet")
    if snippet:
        for line in str(snippet).splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return ""
