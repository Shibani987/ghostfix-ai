# GhostFix Closed Beta Guide

This guide is for 2-5 developers trying GhostFix locally before a public GitHub
release. The goal is careful feedback, not production claims.

## Who Should Try GhostFix

Good beta users are developers who:

- run Python scripts or local dev servers often
- are comfortable reading terminal output
- want local-first diagnosis without copying logs into a chat window
- can report where the diagnosis was helpful or misleading

## Best Use Cases

- Python tracebacks
- Django, Flask, and FastAPI startup/runtime failures
- local watch-mode diagnosis for dev servers
- checking whether a deterministic allowlisted patch is available
- using dry-run to preview behavior before trusting auto-fix

## What Not To Expect

- no enterprise production readiness claim
- no broad autonomous coding
- no broad JavaScript, TypeScript, PHP, or Node auto-fix outside the explicit guarded allowlists
- no dependency installation
- no multi-file project refactors
- no guarantee that Brain v4 is available or fast on every laptop

## Install Steps

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
ghostfix doctor
ghostfix beta-check
```

## First 5 Commands

```powershell
ghostfix quickstart
ghostfix examples
ghostfix run tests/manual_errors/name_error.py
ghostfix run tests/manual_errors/json_empty_v2.py --fix --dry-run
ghostfix watch "python demos/python_name_error.py"
```

## Dry-Run

Dry-run diagnoses normally but does not modify files:

```powershell
ghostfix run tests/manual_errors/name_error.py --dry-run
ghostfix run tests/manual_errors/json_empty_v2.py --fix --dry-run
ghostfix watch "python demos/python_name_error.py" --dry-run
```

Look for:

```text
DRY_RUN: enabled
No code will be modified
```

## Rollback

If a safe fix was applied and backup metadata exists:

```powershell
ghostfix rollback last
```

GhostFix asks before restoring the backup and does not delete the backup file.

## Local Feedback

```powershell
ghostfix feedback --good
ghostfix feedback --bad --note "wrong root cause"
```

Feedback is saved locally in `.ghostfix/feedback.jsonl`.

## What Users May Share Manually

Beta users may choose to share:

- command used
- terminal output copied manually
- `.ghostfix/incidents.jsonl` rows after reviewing them
- `.ghostfix/fix_audit.jsonl` rows after reviewing them
- a small reproduction file or fixture

Review anything before sharing. Remove private paths, tokens, secrets, customer
data, and proprietary code.

## What GhostFix Never Uploads Automatically

GhostFix does not automatically upload:

- source code
- logs
- incidents
- feedback
- audit history
- reports
- model output

Local files stay local unless a user manually shares them.
