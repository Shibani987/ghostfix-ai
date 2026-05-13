# Manual Server Error Examples

These examples intentionally fail so GhostFix watch mode can be checked against server-style tracebacks.

Run from the repository root:

```powershell
python -m cli.main watch "python tests/manual_server_errors/django_missing_app/manage.py runserver"
python -m cli.main watch "python tests/manual_server_errors/flask_missing_template.py"
python -m cli.main watch "uvicorn tests.manual_server_errors.fastapi_bad_import:app --reload"
```

Extra Django settings misconfiguration example:

```powershell
python -m cli.main watch "python tests/manual_server_errors/django_bad_settings.py"
```

Expected GhostFix checks:

- framework
- error type
- root cause
- evidence
- suggested fix
- no duplicate spam

Notes:

- These are lightweight fixtures and do not require database setup.
- They require the relevant framework package to be installed for that framework-specific error to appear.
- If a framework is not installed, Python will fail earlier with `ModuleNotFoundError` for that framework package.
