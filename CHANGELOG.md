# Changelog

All notable public-release changes are tracked here.

## 0.3.0 - 2026-05-13

### Added

- JavaScript, Node.js, React, TypeScript, and Next.js dev-log diagnosis.
- Framework-aware Next.js context detection from `package.json`, `next.config.*`, `tsconfig.json`, `app/`, `pages/`, and `src/`.
- Structured suggestions for Next.js module resolution failures, missing environment variables, build/syntax errors, TypeScript type errors, port conflicts, and hydration-style messages.
- Watch examples for `npm run dev`, `pnpm dev`, and `next dev`.

### Safety

- Non-Python auto-fix remains disabled. JavaScript, TypeScript, React, Next.js, Node.js, PHP, and framework configuration fixes are suggestion-only.
- GhostFix does not run `npm install`, `pnpm install`, or package-manager install commands automatically.
- Python deterministic auto-fix remains safety-gated with patch preview, validation, backup, audit, and rollback metadata.
- Brain, local LLM, and retriever confidence still cannot bypass the safety policy.

## 0.2.0 - 2026-05-09

### Added

- Local-first `ghostfix` CLI packaging.
- Productized first-run setup with `ghostfix setup`.
- Reproducible demo flow with `ghostfix demo`.
- Modern README landing page, demo asset guidance, and GitHub release template.
- Reliability core v1 with structured streaming log events and bounded noisy-log handling.
- Repo-aware context command for project root, framework, dependency, and related-file discovery.
- Release verification command for local production-minded gates.
- Production validation command with JSON/Markdown readiness reports.
- Python runtime diagnosis with safety-gated deterministic auto-fix.
- Watch mode for terminal and dev-server commands.
- Local incident history in `.ghostfix/incidents.jsonl`.
- Foreground daemon v1 with `ghostfix daemon start/status/stop`.
- Doctor, demo report, and benchmark support.
- Optional guarded Brain v4 runtime routing.
- GitHub Actions CI for unit and integration tests.

### Safety

- Brain v4 remains optional and advisory.
- Auto-fix remains limited to deterministic safe Python patches.
- Auto-fix validates patches in a temporary sandbox before applying them to real files.
- Non-Python and framework configuration fixes remain diagnosis-only.

### Notes

- Heavy Brain/base model artifacts are not intended for Git commits.
- Optional Brain model files can be downloaded locally when needed.
