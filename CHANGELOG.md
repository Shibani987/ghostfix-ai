# Changelog

All notable public-release changes are tracked here.

## 0.6.0 - 2026-05-13

### Added

- Runtime/tooling diagnosis for missing package managers, runtimes, executables, project-root files, and framework entrypoints.
- Preflight watch checks for common wrong-directory cases before launching long-running commands.
- Explicit deterministic error types such as `PnpmNotInstalledError`, `PhpRuntimeMissingError`, `DjangoManagePyMissingError`, `UvicornNotInstalledError`, `FlaskAppDiscoveryError`, `PackageJsonMissingError`, `MissingEntryPointError`, and `InvalidProjectRootError`.
- Guarded create-file preview for a minimal `package.json` when a package-manager command is run outside a Node project.

### Safety

- GhostFix still does not install packages, edit secrets, start services, or create full framework projects.
- Project setup creation remains allowlisted, diff-previewed, confirmation-gated, audited, and rollback-capable.

## 0.5.0 - 2026-05-13

### Added

- Command-aware runtime inference for Python scripts, Django, Flask, FastAPI/Uvicorn, Node/Express, Next.js, React/Vite, TypeScript builds, PHP, and Laravel-style local serve commands.
- Unified watch diagnosis fields for language, framework, runtime, failing file/line, evidence, suggested fix, auto-fix availability, block reason, and rollback availability.
- Framework-specific suggestions for Django, Flask, FastAPI/Uvicorn, Next.js, React/Vite, Node/Express, TypeScript, PHP, and Laravel startup/runtime logs.
- Guarded PHP missing-semicolon patch previews validated with `php -l` when PHP is available.

### Safety

- Auto-fix remains allowlisted, deterministic, diff-previewed, backed up, audited, and rollback-capable.
- Risky framework/config/service errors remain suggestion-only.
- GhostFix still never installs dependencies or edits auth, database, payment, security, secret, `.env`, or deployment configuration files automatically.

## 0.4.0 - 2026-05-13

### Added

- Broader multi-language structured diagnosis for Python, JavaScript, TypeScript, Node.js, Express, React, Next.js, Django, Flask, and FastAPI logs.
- Live Next.js/Node runtime diagnosis for Ollama failures, `ECONNREFUSED`, fetch failures, missing env vars, API route 500s, port conflicts, hydration errors, invalid hook calls, module/import/export issues, and TypeScript errors.
- Framework-aware suggestions for Next.js API routes, `.env.local`, external service URLs, React render/hook problems, Express middleware/config issues, and Node module/import failures.
- Guarded JS/TS patch previews for narrow allowlisted fixes, currently missing semicolon repair and exact relative import extension repair.

### Safety

- Python deterministic auto-fix remains the mature path.
- JS/TS guarded fixes require exact local targets, patch preview, confirmation, backup, audit, and rollback metadata.
- GhostFix still does not install packages, edit secrets, modify `.env`, start services, or auto-edit auth, database, payment, network, or security-sensitive code.
- Brain, local LLM, and retriever confidence still cannot bypass the safety policy.

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
