# GhostFix Trust And Safety

GhostFix is designed to stay installed in a local developer workflow without
surprises. Diagnosis is the default. File edits are narrow, explicit, audited,
and reversible when a backup exists.

## Dry-Run Behavior

Use dry-run when you want normal diagnosis and patch preview behavior without
any chance of a file write:

```powershell
ghostfix run tests/manual_errors/name_error.py --dry-run
ghostfix run tests/manual_errors/json_empty_v2.py --fix --dry-run
ghostfix watch "python demos/python_name_error.py" --dry-run
ghostfix watch "python demos/python_name_error.py" --fix --dry-run
```

Dry-run prints:

```text
DRY_RUN: enabled
No code will be modified
```

Dry-run does not apply patches, does not create backups, and does not rerun a
fixed command. It may still record local diagnosis and audit rows.

## Rollback Guarantees

When GhostFix applies a safe fix, it creates a backup and records rollback
metadata in the latest local incident. Use:

```powershell
ghostfix rollback last
```

Rollback asks before restoring and does not delete the backup file.

## Audit History

Auto-fix decisions are recorded locally in:

```text
.ghostfix/fix_audit.jsonl
```

Each row includes:

- timestamp
- target file
- backup path
- patch summary
- validator result
- rollback availability
- whether the user confirmed the change

Read recent audit history with:

```powershell
ghostfix audit
ghostfix audit --last 10
```

## Deterministic Safety Policy

Auto-fix remains limited to deterministic allowlisted patches that pass
validation. Python is the mature path. JS/TS support is intentionally tiny and
limited to exact one-line source repairs such as a missing semicolon or an exact
relative import extension when the target file already exists. PHP support is
limited to simple missing-semicolon repair and uses `php -l` when PHP is
available.

Brain output, retriever matches, confidence values, or local model suggestions
cannot bypass the safety policy.

## What GhostFix Refuses To Change

GhostFix does not auto-edit:

- JavaScript, TypeScript, PHP, or Node files outside the explicit JS/TS/PHP allowlist
- framework configuration with project intent
- dependency installation
- database operations
- network calls
- secrets and environment files
- destructive filesystem operations
- broad multi-file changes

## Why Unsafe Fixes Are Blocked

Some errors need developer judgment or project context. In those cases GhostFix
prints:

```text
Auto-fix blocked by safety policy.
Manual review recommended.
No code was modified.
```

This is expected behavior. The tool should prefer a clear diagnosis over a risky
edit.

## JS/TS Guarded Fixes

When a JS/TS fix is allowlisted, GhostFix shows a patch preview first. Applied
fixes require confirmation, create a backup, write an audit row, and include
rollback metadata for `ghostfix rollback last`.

GhostFix still will not:

- run `npm install`, `pnpm install`, or `yarn install`
- create or edit `.env` or `.env.local`
- start local services such as Ollama
- change auth, database, payment, network, or security-sensitive code
- apply framework config changes automatically

Tooling/setup fixes are limited to safe local file creation such as a minimal
`package.json`, `.env.example`, `__init__.py`, or an empty template file after
preview and confirmation. GhostFix will not create full framework projects or
guess business logic.
