# GhostFix Quickstart

This is the two-minute local path for trying GhostFix.

## 1. First-Time Setup

```powershell
ghostfix setup
```

Setup creates `.ghostfix/config.json` with local-only defaults. No API key is
required, telemetry is disabled, and Brain mode stays off unless you opt in.

## 2. Verify Install

```powershell
ghostfix --version
ghostfix doctor
```

Doctor explains the local environment, local-only mode, optional Brain support,
safety policy, rollback support, and where GhostFix stores local files.

## 3. Run A First Diagnosis

```powershell
ghostfix run app.py
ghostfix run tests/manual_errors/name_error.py
```

GhostFix runs the file, reads the traceback, and prints a short diagnosis with a
next step. No code is changed.

## 4. Run The Product Demo

```powershell
ghostfix demo
```

The demo creates a temporary crashing Python file and runs in dry-run mode so no
code is modified.

## 5. Try A Guarded Auto-Fix Preview

```powershell
ghostfix run tests/manual_errors/json_empty_v2.py --fix
```

Auto-fix is intentionally narrow. GhostFix shows a patch only when the existing
safety policy allows it. If a fix is applied, a backup is kept.

## 6. Watch A Local Dev Command

```powershell
ghostfix watch "python demos/python_name_error.py"
ghostfix watch "python demos/django_like/manage.py runserver"
ghostfix watch "python demos/fastapi_like/main.py"
ghostfix watch "npm run dev" --cwd demos/node_like
```

Watch mode streams output and diagnoses the first runtime failure it can
recognize.

## 7. Roll Back An Applied Fix

```powershell
ghostfix rollback last
```

Rollback restores the latest applied-fix backup when the latest incident has
rollback metadata. GhostFix asks before restoring and does not delete backups.

## 8. Leave Local Feedback

```powershell
ghostfix feedback --good
ghostfix feedback --bad --note "wrong root cause"
```

Feedback is stored locally in `.ghostfix/feedback.jsonl`.

## Local Storage

- incidents: `.ghostfix/incidents.jsonl`
- feedback: `.ghostfix/feedback.jsonl`
- fix audit: `.ghostfix/fix_audit.jsonl`
- reports: `.ghostfix/reports/`
- daemon state: `.ghostfix/daemon.json`

GhostFix does not require a cloud account for local diagnosis.
