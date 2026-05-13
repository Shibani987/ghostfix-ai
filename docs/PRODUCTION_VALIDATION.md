# Production Validation

GhostFix includes a repeatable local validation suite for release readiness.

Run:

```powershell
ghostfix validate-production
```

The command writes:

```text
.ghostfix/reports/production_validation.json
.ghostfix/reports/production_validation.md
```

## What It Runs

- `ghostfix verify-release`
- `ghostfix doctor`
- `ghostfix config show`
- `ghostfix context demos/python_name_error.py`
- `ghostfix run tests/manual_errors/name_error.py`
- `ghostfix watch "python demos/python_name_error.py" --no-brain`
- `python ml/evaluate_watch_mode.py`
- `python ml/evaluate_runtime_brain_v4.py --dir tests/real_world_failures --brain-mode route-only`

## What Passing Means

Passing means the local CLI can install/run in the current environment, core commands execute, watch-mode benchmarks complete, route-only Brain v4 evaluation completes, and no validation step reported a release blocker.

The report summarizes:

- tests passed
- CLI commands passed
- benchmark metrics
- unresolved rate
- unsafe fix rate
- release blockers

## What Passing Does Not Mean

Passing does not mean GhostFix is a fully autonomous debugger, enterprise incident platform, or unrestricted auto-fixer. It does not prove correctness on every framework, monorepo, private codebase, or production log source.

Use this validation as a release gate for the local CLI candidate, then continue real-user testing on diverse projects.
