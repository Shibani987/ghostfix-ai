# Demo Commands

Run these from the repository root.

## Basic CLI

```powershell
ghostfix setup
ghostfix demo
ghostfix run tests/manual_errors/name_error.py --dry-run
ghostfix run tests/manual_errors/name_error.py --verbose
ghostfix run tests/manual_errors/json_empty_v2.py --fix
```

## Watch Mode

```powershell
ghostfix watch "python demos/python_name_error.py" --dry-run
ghostfix watch "python demos/django_like/manage.py runserver" --dry-run
ghostfix watch "python demos/fastapi_like/main.py" --dry-run
ghostfix watch "npm run dev" --cwd demos/node_like
```

## Repo Context

```powershell
python -m cli.main context tests/manual_errors/name_error.py
```

## Incident History

```powershell
python -m cli.main incidents
python -m cli.main incidents --last 10
```

## Daemon Mode

```powershell
python -m cli.main daemon start "python demos/python_name_error.py"
python -m cli.main daemon status
python -m cli.main daemon stop
```

## Brain v4 Check

```powershell
python ml/check_brain_v4_model.py
```

## Benchmarks

```powershell
python -m cli.main verify-release
python -m cli.main validate-production
python ml/evaluate_watch_mode.py
python ml/evaluate_runtime_brain_v4.py --dir tests/real_world_failures --brain-mode route-only
python ml/evaluate_runtime_brain_v4.py --dir tests/brain_escalation_cases --brain-mode route-only
```
