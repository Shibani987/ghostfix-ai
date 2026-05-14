# GhostFix Enterprise Readiness

## Current Status

GhostFix is an enterprise-evaluation-ready local debugging CLI candidate. It is suitable for serious local developer evaluation from PyPI when all release gates pass, but it is not a full hosted enterprise platform and should not be marketed as one.

## Enterprise-Ready Today

- Local-first CLI operation with no automatic cloud telemetry.
- Deterministic auto-fix only for narrow allowlists, with Python as the mature path.
- Safety policy remains the final auto-fix gate.
- Dry-run mode for diagnosis without file writes.
- Local backup and rollback metadata for applied fixes.
- Local audit records for auto-fix decisions.
- Bounded watch-mode log buffering and duplicate incident suppression.
- PyPI packaging with a `ghostfix` console command.

## Enterprise-Style But Still Beta

- Brain v4 routing/generation is optional and advisory.
- Watch mode handles noisy and long-running local logs, but is not production observability.
- Non-Python languages are diagnosis-first with only tiny guarded allowlisted patch paths.
- Release validation provides local readiness evidence, not a compliance certification.

## Explicitly Not Supported

- Broad JavaScript, TypeScript, or PHP auto-fix.
- Brain/LLM/retriever confidence enabling auto-fix.
- Unrestricted autonomous code editing.
- Cloud telemetry by default.
- Silent upload of code, logs, incidents, snippets, feedback, or exports.
- Hosted incident management, SSO, RBAC, fleet policy, or centralized observability.

## Security And Privacy Posture

GhostFix stores runtime state locally under `.ghostfix/` and local ML feedback under `.ml/` when used. These paths are ignored by Git and excluded from release artifacts. Project context scanning avoids `.env`, secret-named files, private keys, local databases, `.ghostfix/`, `.ml/`, model folders, generated reports, and common caches. Training exports are explicit, local, and redacted.

## Safety Guarantees

- Dry-run never applies patches.
- Auto-fix requires a deterministic allowlisted patch; Python is the mature path.
- Validation runs before real file modification.
- Backups are created before modification.
- Rollback restores from recorded backup metadata with confirmation.
- Failed validation does not apply the patch.
- Model output can explain or route, but cannot grant auto-fix permission.

## Validation Commands

```powershell
python -m unittest discover tests
ghostfix doctor
ghostfix verify-release
ghostfix validate-production
ghostfix beta-check
python -m build
python -m twine check dist/*
```

`validate-production` means local release validation. Passing it supports an enterprise-evaluation-ready claim only.

## Remaining Blockers Before Full Enterprise Readiness

- Signed releases and provenance attestations.
- Formal security review and vulnerability response SLA.
- Organization policy management, RBAC, SSO, and audit export controls.
- Cross-platform installer testing beyond the current Python package flow.
- Documented support matrix for large repositories and shell environments.
- Hardened optional integration contracts if cloud or hosted integrations are added later.

## Recommended Path To v1.0

1. Keep auto-fix limited to deterministic validated allowlisted patches, with Python as the mature path.
2. Stabilize CLI JSON outputs and exit-code contracts.
3. Add signed release automation and release provenance.
4. Expand Windows, macOS, and Linux smoke coverage in CI.
5. Publish a clear support matrix and enterprise evaluation guide.
6. Add opt-in enterprise controls only after local-first safety remains stable.
