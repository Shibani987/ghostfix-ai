# Production Readiness

GhostFix is a production-minded local CLI MVP for developer debugging loops. It is not yet a fully autonomous enterprise debugger.

## Current Strengths

- Local-first CLI install with `ghostfix` console commands.
- Watch mode for noisy terminal and dev-server logs.
- Reliability core v1 with structured log events, partial traceback grouping, unicode-safe decoding, and bounded buffers.
- Repo-aware context discovery for project roots, dependency files, frameworks, and related local files.
- Local-only configuration and incident history without private cloud credentials.
- Local production-like log classification for explicit user-provided files, including auth anomaly, repeated failure, infrastructure, dependency, and app bug categories.
- Disabled-by-default Sentry, PostHog, and Clarity interface stubs for future explicit integrations.
- Safety-gated deterministic Python auto-fix with patch preview, backup, user confirmation, sandbox validation, and rollback metadata.
- Optional Brain v4 routing that remains advisory and cannot bypass safety policy.
- Release and production validation commands for local pre-push checks.

## Current Limitations

- Python is the mature path; JavaScript, TypeScript, Node, and PHP are diagnosis-first with only tiny guarded patch allowlists.
- Repo-aware context is intentionally bounded and may miss deep project conventions.
- Daemon v1 runs foreground-first and is not a full service manager.
- Brain v4 requires compatible local model files and optional ML dependencies.
- Auto-fix is deliberately narrow and does not perform broad refactors or multi-file changes.
- Release and production validation are local smoke gates, not replacements for CI, security review, or real-user validation.
- Production telemetry integrations are not live today. GhostFix does not monitor production systems, fetch hosted telemetry, or use API keys unless a future explicit integration is built and configured by the user.

## Production Checklist

- Run `python -m unittest discover tests`.
- Run `ghostfix verify-release`.
- Run `ghostfix validate-production`.
- Confirm `.env`, `.ghostfix/`, `.ml/`, reports, caches, backups, and model weights are not committed.
- Confirm optional Brain model files are documented but not required for base CLI use.
- Use `ghostfix doctor` to inspect local environment readiness.
- Use `ghostfix context <file>` before relying on repo-aware diagnosis.
- Review every patch preview before confirming auto-fix.

## What Is Safe

- Diagnosis from local logs and bounded repo context.
- Reading allowlisted project/dependency/config files while ignoring secret paths.
- Deterministic Python auto-fixes that pass sandbox validation, syntax checks, backup creation, and user confirmation.
- Local incident history for debugging sessions.
- Local classification of production-like logs that the user explicitly provides.
- Integration stubs that normalize local event-shaped objects without network calls.

## What Is Experimental

- Brain v4 generation quality and speed on CPU.
- Long-running daemon workflows beyond foreground v1.
- Related-file collection beyond common local imports and framework config files.
- Release and production validation as convenience gates.
- Production signal classification rules before real-world telemetry calibration.
- Sentry/PostHog/Clarity architecture hooks; they are placeholders, not working hosted integrations.

## Needs Real-User Validation

- Larger Django, FastAPI, Flask, Vite, Next.js, and mixed Python/Node repositories.
- Repeated-failure grouping across long-running dev sessions.
- Context relevance across monorepos.
- False-positive and false-negative rates on real user logs.
- Whether production-like event classification thresholds match real incidents.
- Explicit opt-in telemetry import flows for future Sentry, PostHog, or Clarity support.
- Windows, macOS, and Linux install paths after public release.
