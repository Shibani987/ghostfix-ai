# Contributing

Thanks for helping improve GhostFix. This project is a local-first CLI debugging assistant, so contributions should keep behavior predictable, testable, and safe by default.

## Development Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m unittest discover tests
```

## Contribution Guidelines

- Keep changes focused and include tests for user-facing behavior.
- Do not retrain models as part of normal code contributions.
- Do not change Brain v4 behavior unless the issue or PR is explicitly about Brain v4.
- Do not weaken safety policy or expand auto-fix behavior without tests and clear documentation.
- Keep generated reports, local state, model checkpoints, and environment files out of commits.
- Prefer deterministic rules and local evidence before model-backed behavior.

## Testing

Run the full suite before opening a PR:

```powershell
python -m unittest discover tests
```

Useful manual checks:

```powershell
ghostfix doctor
ghostfix run tests/manual_errors/name_error.py
ghostfix watch "python demos/python_name_error.py"
ghostfix incidents
```

## Documentation

Update `README.md` and files under `docs/` when changing CLI commands, setup steps, safety behavior, release process, or public limitations.

## Pull Requests

Please include:

- A short summary of the change.
- The test command you ran and result.
- Any known limitations or follow-up work.
- Confirmation if the change intentionally avoids model logic, retraining, and safety policy changes.
