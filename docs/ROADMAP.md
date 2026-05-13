# Roadmap

## Current MVP

- Promptless runtime diagnosis from terminal logs.
- Reliability core v1 for structured streaming log events, partial tracebacks, and bounded noisy logs.
- Repo-aware context v1 for project roots, framework hints, dependency files, and safe related-file collection.
- Python traceback support.
- Django, Flask, FastAPI, and Uvicorn diagnosis.
- Early JavaScript, Node.js, TypeScript-style, and PHP diagnosis.
- Watch mode for terminal and server processes.
- Foreground daemon v1 for continuously monitoring a dev command.
- Local incident memory with repeated adjacent duplicate suppression.
- Local production-like event classification and anomaly rules for user-provided log files.
- Disabled-by-default Sentry, PostHog, and Clarity architecture hooks.
- Small deterministic Python auto-fix behind safety gates.
- Optional Brain v4 routing and generation for harder cases.
- Watch mode and Brain routing benchmarks.

## Next: Daemon Polish + Incident Summaries

- Background process handoff beyond the foreground v1 loop.
- Better persistent incident summaries.
- Repeated-failure grouping.
- Better production-like classifier calibration against explicit user-provided logs.
- Local summaries of recurring project issues.
- Safer defaults for long-running watch sessions.
- More reliability benchmarks for file and docker-like log streams.
- More real-world validation of repo-aware context relevance.

## Later: VS Code Extension

- Editor panel for diagnoses.
- Clickable source locations.
- Patch previews inside the editor.
- Watch mode controls from VS Code.
- Local settings for Brain mode and safety preferences.

## Later: Repo-Aware Multi-File Fixes

- Broader project context.
- Import graph and framework config awareness.
- Multi-file patch planning.
- Stronger validation before edits.
- Clear review flow before applying changes.

## Later: Stronger Local Model

- Better local reasoning for hard runtime failures.
- More robust Brain compatibility tooling.
- Faster CPU and GPU paths.
- Better malformed-output handling.
- Expanded evaluation sets before promotion.

## Later: CI/CD And Observability Integrations

- CI failure diagnosis.
- Structured report export for build systems.
- Explicit opt-in integration with local and hosted log sources.
- Sentry, PostHog, and Clarity event import after API access, privacy behavior, and user consent flows are designed.
- Incident-style timelines.
- Team-friendly reporting without weakening local-first safety.

## Not Claimed Yet

- GhostFix does not secretly monitor production systems.
- GhostFix does not currently call Sentry, PostHog, Clarity, or other telemetry APIs.
- Future production telemetry mode would require explicit user-provided logs, events, files, or API credentials.
