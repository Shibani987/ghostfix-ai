# GhostFix Demo Assets

Use these shots for the README, GitHub releases, hackathon submissions, and short social clips.

## Core GIF

Length: 30-45 seconds.

```bash
pip install ghostfix-ai
ghostfix setup
ghostfix demo
```

What viewers should see:

- Local-only setup.
- No API key required.
- A real Python crash.
- A compact diagnosis.
- A dry-run safety message.
- Clear "No code was modified" output.

## Watch Mode Clip

Length: 20-30 seconds.

```bash
ghostfix watch "python demos/python_name_error.py" --dry-run
```

Show GhostFix streaming terminal output, detecting the traceback, and producing the status block.

## Trust Clip

Length: 20-30 seconds.

```bash
ghostfix run tests/manual_errors/json_empty_v2.py --fix
ghostfix audit --last 5
ghostfix rollback last
```

Narration:

- Auto-fix is narrow.
- A backup is created before modification.
- Audit records explain what happened.
- Rollback is explicit and confirmed.

## Framework Clips

Flask:

```bash
ghostfix watch "python tests/manual_server_errors/flask_missing_template.py" --dry-run
```

FastAPI:

```bash
ghostfix watch "python demos/fastapi_like/main.py" --dry-run
```

Django:

```bash
ghostfix watch "python demos/django_like/manage.py runserver" --dry-run
```

Plain Python:

```bash
ghostfix run tests/manual_errors/name_error.py --dry-run
```

## Recording Notes

- Use `--no-color` for documentation screenshots when ANSI output is distracting.
- Use dry-run for public demos unless the point is specifically backup and rollback.
- Keep the terminal width at 90-110 columns.
- Do not show real project secrets, `.env` files, private logs, or proprietary source.
- Do not claim broad JavaScript, TypeScript, or PHP auto-fix; only tiny guarded allowlisted patch previews are supported.
