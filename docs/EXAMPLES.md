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

## Node

```powershell
ghostfix watch "npm run dev"
ghostfix watch "npm run dev" --cwd demos/node_like
```

Node and browser-style JavaScript errors are diagnosis-only in the current
release.

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
