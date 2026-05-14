# Changelog

All notable public-release changes are tracked here.

## 1.0.0 - 2026-05-14

### Added

- Validation-driven autonomous debugging agent for supported Python, Django, Flask, FastAPI, Node/Express, Next.js, React, and TypeScript workflows.
- Bounded sandbox tool-use engine that can inspect repo graphs, package metadata, TypeScript config, routes, imports, exports, components, entrypoints, and validation reruns without touching the real project.
- Multi-candidate patch generation and ranking for up to 3 safe candidates using validation success, regression score, confidence, repo consistency, and rerun output quality.
- Max 3-loop autonomous repair convergence with duplicate-failure, regression, and confidence-collapse stop conditions.
- Repo graph intelligence now includes import, export, route, component, and entrypoint graphs.
- Autonomous benchmark report metrics for solve rate, regression rate, validation success rate, retry success rate, and unresolved rate.

### Safety

- Validation remains the authority: no real patch is applyable unless sandbox validation passes, rerun output is clean, regression checks pass, and rollback-capable file metadata exists.
- Auth, payment, database schema/migration, secret, `.env`, deployment, package-install, infrastructure, and security-sensitive changes remain blocked.
- PHP remains legacy diagnosis/simple guarded preview support only and is not part of the v1 autonomous agent.

## 0.9.0 - 2026-05-14

### Added

- Iterative validation-first debugging engine for supported Python, Django, Flask, FastAPI, Node/Express, Next.js, React, and TypeScript workflows.
- Sandbox retry loop with max 2 retries, duplicate-failure suppression, confidence-drop stop conditions, regression detection, retry telemetry, and patch confidence scoring.
- Framework-aware validation command selection for Python compile/rerun, JS/TS `npm run build`, `tsc --noEmit`, and targeted reruns when available.
- Repo context graph payloads for iterative runs, including imports, exports, routes, app entrypoints, and framework structure.
- Multi-file rollback verification metadata for converged iterative patches.

### Safety

- Validation always dominates generation: no iterative patch is offered unless sandbox validation converges.
- Auth, payment, database migration, secret, `.env`, deployment, security-sensitive, package-install, and external-service changes remain blocked.
- Retry loops stop on duplicate failures, unparsed failures, confidence drops, or regressions.

## 0.8.0 - 2026-05-14

### Added

- Codex-like local framework fixer path for supported runtime/dev-server errors.
- Guarded Next.js Ollama route fixer that maps `/api/generate-resume` to the local route and `resumeAgent.ts`, adds an Ollama preflight against `/api/tags`, checks the configured model, adds `OLLAMA_TIMEOUT_MS`, and writes safer non-secret defaults to `.env.example` only.
- Temporary project-copy validation for framework patches with required `npm run build` before a fix is offered.
- Multi-file backup metadata for framework fixes so rollback can restore all changed files.

### Safety

- GhostFix still does not install packages, edit `.env` or secrets, start services, or modify auth, database, payment, security, deployment, or broad framework config automatically.
- Framework fixes require exact local source targets, sandbox validation, project validation, diff preview, user confirmation, audit, and rollback metadata.
- Service/config failures remain blocked unless GhostFix can patch a safe project source guard and validation passes.

## 0.7.0 - 2026-05-14

### Added

- Repo-aware engine coverage for Python, JavaScript/TypeScript, and PHP source snapshots.
- Guarded JS/TS export-mismatch patch previews for exact local default-export or spelling/case repairs.
- Guarded PHP missing-semicolon patch previews with sandbox validation and optional `php -l`.
- Expanded release and beta validation around rollback, trust-and-safety, and package hygiene.

### Safety

- Broad JavaScript, TypeScript, PHP, framework config, dependency install, auth, database, payment, network, secret, and destructive filesystem fixes remain blocked.
- Non-Python edits are limited to explicit deterministic allowlists with patch preview, confirmation, audit, backup or rollback metadata, and sandbox validation.
- Brain, local LLM, and retriever confidence still cannot bypass the safety policy.

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
