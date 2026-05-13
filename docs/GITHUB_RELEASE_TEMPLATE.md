# GhostFix Release Presentation

Use this structure for GitHub releases and PyPI release notes.

## Title

GhostFix AI vX.Y.Z - local-first runtime debugging CLI

## One-Liner

Promptless runtime debugging for developers: watch logs, explain crashes, and apply only safety-gated deterministic Python fixes.

## Highlights

- `ghostfix setup` for local-only first-run configuration.
- `ghostfix demo` for a short reproducible product demo.
- `ghostfix watch` for terminal and dev-server crash detection.
- Safety-gated Python auto-fix with audit and rollback metadata.
- No cloud telemetry or API key required by default.

## Upgrade

```bash
pip install --upgrade ghostfix-ai
ghostfix doctor
ghostfix quickstart
```

## Validation

```bash
python -m unittest discover tests
ghostfix verify-release
ghostfix validate-production
python -m build
python -m twine check dist/*
```

## Honest Scope

GhostFix is enterprise-evaluation-ready as a local debugging CLI candidate. It is not a hosted enterprise platform, autonomous coding agent, or production observability replacement.

JavaScript, TypeScript, and PHP support remain diagnosis-only.
