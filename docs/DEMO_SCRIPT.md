# GhostFix Demo Script

Use this as a 60-90 second video or live hackathon walkthrough. The goal is to show that GhostFix can diagnose real terminal/runtime failures, keep model reasoning guarded, and apply only conservative Python fixes.

## 0:00 - Setup

Say:

GhostFix is promptless runtime debugging for developers. It watches terminal logs, explains crashes, and applies only safety-gated deterministic Python fixes.

Run:

```powershell
ghostfix setup
```

Say:

No API key required. No code leaves your machine. Config is local-only by default.

## 0:15 - Product Demo

Run:

```powershell
ghostfix demo
```

Say:

The demo creates a temporary crashing Python file, detects the failure, shows the likely root cause, previews the safety-gated patch path, and keeps dry-run on so no code is modified.

## 0:45 - Watch Mode

Run:

```powershell
ghostfix watch "python demos/python_name_error.py" --dry-run
```

Say:

Watch mode streams the process output and opens a diagnosis when it sees a real traceback.

## 1:05 - Trust Loop

Run:

```powershell
ghostfix audit
ghostfix rollback last
```

Say:

Applied fixes create backups and audit records. Rollback is explicit and confirmed.

## Optional Longer Flow

Run:

```powershell
ghostfix run tests/manual_errors/name_error.py --dry-run
ghostfix run tests/manual_errors/json_empty_v2.py --fix
ghostfix watch "python demos/django_like/manage.py runserver" --dry-run
ghostfix watch "python demos/fastapi_like/main.py" --dry-run
ghostfix watch "npm run dev" --cwd demos/node_like
```

Say:

GhostFix is designed for practical debugging: readable diagnoses first, guarded model escalation only when enabled, and conservative safety-gated fixes.
