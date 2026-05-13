# GhostFix Examples

These examples are local commands you can run after installing GhostFix.

## Setup And Demo

```powershell
ghostfix setup
ghostfix doctor
ghostfix quickstart
ghostfix demo
```

## Python Script

```powershell
ghostfix run app.py
ghostfix run tests/manual_errors/name_error.py
ghostfix run tests/manual_errors/json_empty_v2.py --fix
```

## Django

```powershell
ghostfix watch "python manage.py runserver"
ghostfix watch "python demos/django_like/manage.py runserver"
```

## FastAPI

```powershell
ghostfix watch "uvicorn main:app --reload"
ghostfix watch "python demos/fastapi_like/main.py"
```

## Flask

```powershell
ghostfix watch "python app.py"
ghostfix watch "flask run"
```

## Node, Next.js, React, And TypeScript

```powershell
ghostfix watch "npm run dev"
ghostfix watch "pnpm dev"
ghostfix watch "next dev"
ghostfix watch "npm run dev" --cwd demos/node_like
```

GhostFix detects common Node, Next.js, React, and TypeScript dev-server errors,
including module-not-found, missing environment variables, build/syntax errors,
port conflicts, TypeScript type errors, and hydration-style messages.

These errors are diagnosis-only in the current release. GhostFix prints a
suggested fix, but it does not edit JavaScript or TypeScript files and it does
not run package-manager install commands.

## Rollback

```powershell
ghostfix rollback last
```

Use rollback after an applied safe fix if you want to restore the latest backup.

## Audit

```powershell
ghostfix audit
ghostfix audit --last 10
```

Audit history is local and records auto-fix confirmations, validator results,
patch summaries, and rollback availability.

## Feedback

```powershell
ghostfix feedback --good
ghostfix feedback --bad --note "wrong root cause"
```

Feedback stays local and is attached to the latest incident summary when one
exists.
