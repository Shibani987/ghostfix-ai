# Safety

GhostFix is intentionally conservative. It diagnoses many errors, but it only edits code through narrow deterministic allowlists. Python is the mature path; JS/TS and PHP edits are tiny guarded patch paths only.

## Auto-Fix Is Limited

Auto-fix is not a general model-powered rewrite system. It is allowed only when GhostFix has a deterministic patch plan for an allowlisted error type and validation passes.

Examples of blocked cases include:

- Missing packages.
- Framework configuration.
- Project-specific runtime behavior.
- Data-shape or business-logic ambiguity.
- JavaScript, TypeScript, Node.js, and PHP errors outside the explicit guarded allowlists.
- Any case where the patch cannot be validated safely.

## Backups Are Created

Before applying a fix, GhostFix creates a backup next to the edited file:

```text
example.py.bak_YYYYMMDD_HHMMSS
```

Backup files are intentionally ignored by Git using `*.bak_*`.

## Sandbox Validation Comes First

Before an auto-fix is applied to the real file, GhostFix applies the patch to a temporary sandbox copy and validates the resulting Python with `ast.parse`, `compile`, and local compile checks. If the sandbox result fails, the real file is not touched.

Incident history stores rollback metadata for patch attempts, including backup location when a real patch is applied.

## No Destructive Fixes

GhostFix does not use auto-fix to delete files, remove broad code sections, rewrite project configuration, install packages, or perform destructive migrations.

## Non-Python Fixes Are Tiny Guarded Allowlists

JavaScript, TypeScript, Node.js, and PHP support is mostly for detection and explanation. GhostFix may offer a patch only for explicit low-risk allowlisted cases such as JS/TS one-line repairs or PHP missing-semicolon repair. Framework config, dependencies, services, auth, database, payment, network, secrets, and project-intent changes remain suggestion-only.

## Brain Output Is Advisory And Guarded

Brain v4 can help with hard or unfamiliar cases, but its output does not override safety policy. A Brain suggestion cannot make an unsafe fix safe.

GhostFix may suppress Brain output when it is unavailable, malformed, too generic, low-confidence, conflicting, or blocked by policy.

## Safe Fix Policy

A fix can be applied only when:

- The language and patch kind are in the explicit allowlist.
- The error type is allowlisted for deterministic auto-fix.
- A concrete patch plan exists.
- The patch does not change unrelated lines.
- The patch passes temporary sandbox validation.
- The generated file still parses as Python.
- The patch passes validation.
- A backup is created first.
- The user confirms the fix unless an explicit auto-approve flow is used.

This policy is part of the product, not a temporary limitation.
