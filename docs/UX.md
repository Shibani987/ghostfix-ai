# GhostFix CLI UX

GhostFix output is designed to be readable in two layers:

1. Plain summary lines that do not depend on Rich table or panel rendering.
2. Rich panels and tables with detailed diagnosis, evidence, and safety data.

## Output Structure

Common commands print stable plain lines such as:

```text
STATUS: error
ERROR: NameError
ROOT_CAUSE: A variable or function is used before it is defined.
NEXT_STEP: review the diagnosis and update the code manually
AUTO_FIX: no
ROLLBACK_AVAILABLE: no
```

Human-friendly variants are also printed:

```text
Next step: review the diagnosis and update the code manually
Auto-fix available: no
Rollback available: no
```

These lines are intentionally simple so they remain useful in terminals, logs,
screenshots, and wrapped CI output.

## Diagnosis Language

Diagnosis output should help a developer quickly answer:

- what failed
- why GhostFix thinks it failed
- what evidence was found
- whether a fix is safe to apply automatically
- what to do next

The Rich panel keeps detailed fields such as error type, cause, fix, confidence,
patch preview, and safety information. The plain lines give the quick path.

## Safety Language

GhostFix uses conservative language around code changes:

- `Auto-fix available: yes` means a deterministic, safety-gated patch is
  available for review or application.
- `Auto-fix available: no` means GhostFix is giving diagnosis only.
- `No code was changed` is printed when a patch is not applied.
- `Rollback available: yes` appears only when an applied fix has backup metadata.

## When GhostFix Says No

GhostFix says no to auto-fix when the error may require developer intent,
project context, filesystem knowledge, or runtime data. Examples include many
`NameError`, `KeyError`, `FileNotFoundError`, `RuntimeError`, and permission
failures.

In those cases the next step is manual review. GhostFix should still explain the
likely cause and suggest a safe direction.

## Auto-Fix Blocked

When auto-fix is blocked, output includes the block reason in the detailed
diagnosis panel. Blocking auto-fix does not mean GhostFix failed; it means the
tool chose diagnosis over a risky edit.

## Rollback Workflow

When GhostFix applies a safe fix, it records backup metadata in the latest local
incident. Use:

```powershell
ghostfix rollback last
```

GhostFix asks for confirmation before restoring the backup. It does not delete
the backup file.

If no backup metadata is available, GhostFix prints:

```text
No rollback available for the latest incident.
Rollback available: no
```

## Feedback Workflow

Use local feedback after a diagnosis:

```powershell
ghostfix feedback --good
ghostfix feedback --bad --note "wrong root cause"
```

Feedback is saved to `.ghostfix/feedback.jsonl`. It stays local and is attached
to the latest incident summary when one exists.
