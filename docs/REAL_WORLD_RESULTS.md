# GhostFix Real World Results

| Project | Runtime | Error | Command | Useful? | Correct? | Crash? | Wrong Fix? | Notes |
|---|---|---|---|---|---|---|---|---|
| django_blog | Python/Django-like | missing app / bad INSTALLED_APPS | `ghostfix watch "python manage.py runserver"` | TBD | TBD | TBD | TBD | Run from `tests/real_user_projects/django_blog`. |
| django_blog | Python/Django-like | missing settings import | `ghostfix watch "python manage.py runserver --scenario missing_settings_import"` | TBD | TBD | TBD | TBD | Simulates a missing local settings module. |
| django_blog | Python/Django-like | missing template | `ghostfix watch "python manage.py runserver --scenario missing_template"` | TBD | TBD | TBD | TBD | Raises `TemplateDoesNotExist`. |
| fastapi_api | Python/FastAPI-like | missing dependency import | `ghostfix watch "uvicorn main:app --reload"` | TBD | TBD | TBD | TBD | `python main.py` also reaches the same missing dependency. |
| fastapi_api | Python/FastAPI-like | bad app import/startup | `ghostfix watch "uvicorn bad_app:app --reload"` | TBD | TBD | TBD | TBD | Use `python bad_app.py` if Uvicorn is unavailable. |
| fastapi_api | Python/FastAPI-like | missing environment variable | `ghostfix watch "uvicorn env_app:app --reload"` | TBD | TBD | TBD | TBD | Missing `FASTAPI_API_TOKEN`. |
| flask_shop | Python/Flask-like | TemplateNotFound | `ghostfix watch "python app.py"` | TBD | TBD | TBD | TBD | Run from `tests/real_user_projects/flask_shop`. |
| flask_shop | Python/Flask-like | missing dependency | `ghostfix watch "python app.py --scenario missing_dependency"` | TBD | TBD | TBD | TBD | Missing payment client import. |
| flask_shop | Python/Flask-like | route/runtime exception | `ghostfix watch "python app.py --scenario route_exception"` | TBD | TBD | TBD | TBD | Route-like handler raises `KeyError`. |
| simple_script | Python | NameError | `ghostfix run tests/real_user_projects/simple_script/name_error.py` | TBD | TBD | TBD | TBD | Undefined variable. |
| simple_script | Python | FileNotFoundError | `ghostfix run tests/real_user_projects/simple_script/file_not_found.py` | TBD | TBD | TBD | TBD | Missing config file. |
| simple_script | Python | JSONDecodeError | `ghostfix run tests/real_user_projects/simple_script/json_decode.py` | TBD | TBD | TBD | TBD | Empty JSON response body. |
| node_express | Node/Express-like | missing module | `ghostfix watch "npm run dev"` | TBD | TBD | TBD | TBD | Run from `tests/real_user_projects/node_express`. |
| node_express | Node/Express-like | bad env var | `ghostfix watch "npm run bad-env"` | TBD | TBD | TBD | TBD | Missing `NODE_EXPRESS_API_KEY`. |
| node_express | Node/Express-like | startup crash | `ghostfix watch "npm run startup-crash"` | TBD | TBD | TBD | TBD | Simulates failed route loading. |

## Manual Run Guide

Run all commands from the repository root unless a project-specific directory is
called out. These scenarios are intentionally failing and local-only.

### Django Blog

```powershell
cd tests/real_user_projects/django_blog
ghostfix watch "python manage.py runserver"
ghostfix watch "python manage.py runserver --scenario missing_settings_import"
ghostfix watch "python manage.py runserver --scenario missing_template"
```

### FastAPI API

```powershell
cd tests/real_user_projects/fastapi_api
ghostfix watch "uvicorn main:app --reload"
ghostfix watch "uvicorn bad_app:app --reload"
ghostfix watch "uvicorn env_app:app --reload"
```

If Uvicorn is not installed locally, these fallback commands still exercise the
same fixture failures:

```powershell
ghostfix watch "python main.py"
ghostfix watch "python bad_app.py"
ghostfix watch "python -c `"import env_app`""
```

### Flask Shop

```powershell
cd tests/real_user_projects/flask_shop
ghostfix watch "python app.py"
ghostfix watch "python app.py --scenario missing_dependency"
ghostfix watch "python app.py --scenario route_exception"
```

### Simple Python

```powershell
ghostfix run tests/real_user_projects/simple_script/name_error.py
ghostfix run tests/real_user_projects/simple_script/file_not_found.py
ghostfix run tests/real_user_projects/simple_script/json_decode.py
```

### Node Express

```powershell
cd tests/real_user_projects/node_express
ghostfix watch "npm run dev"
ghostfix watch "npm run bad-env"
ghostfix watch "npm run startup-crash"
```

## Recording Results

After each manual run, update the table:

- `Useful?`: whether GhostFix surfaced actionable context.
- `Correct?`: whether the likely root cause matched the scenario.
- `Crash?`: whether GhostFix itself crashed.
- `Wrong Fix?`: whether GhostFix suggested an unsafe or misleading fix.
- `Notes`: any mismatch, missing context, or follow-up improvement.
