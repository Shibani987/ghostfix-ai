# GhostFix Architecture

GhostFix is a local-first runtime debugging pipeline. It is designed to keep fast deterministic layers in front, use Brain v4 only when useful, and leave safety policy as the final gate before any edit.

## Pipeline

```text
CLI / Watch Mode
  -> structured log-event pipeline
  -> repo-aware context engine
  -> bounded autonomous sandbox agent for supported stacks
  -> production-like signal classifier for user-provided logs
  -> parser / runtime detector
  -> memory / deterministic rules / retriever
  -> guarded Brain v4 escalation
  -> safety policy / validated auto-fix
  -> local incident history
  -> reports and feedback logs
```

## Components

### CLI And Watch Mode

The CLI has three main runtime paths:

- `python -m cli.main run <file>` runs a Python file once and analyzes stderr.
- `python -m cli.main watch "<command>"` starts a real subprocess, streams logs live, detects runtime errors, and shows a compact diagnosis panel.
- `python -m cli.main daemon start "<command>"` runs a foreground monitor loop that reuses Watch Mode and records incidents.
- `python -m cli.main context <file>` shows bounded repo-aware context for a file.
- `python -m cli.main classify-log <log-file>` classifies local production-like log signals without external telemetry calls.
- `python -m cli.main verify-release` runs local release gates.

Watch Mode is promptless by default. It never applies fixes unless `--fix` is passed.

### Reliability Core

GhostFix normalizes streaming process output into structured log events before diagnosis. The log-event pipeline handles:

- subprocess, file, and docker-like stream sources
- partial-line buffering
- multi-line Python traceback grouping
- bounded recent-output buffers
- max event size truncation
- unicode-safe byte decoding
- parser guards so malformed logs do not crash the CLI

This layer is used by Watch Mode so long-running local commands can emit noisy, partial, repeated, or very large logs without destabilizing GhostFix.

### Daemon Mode

Daemon v1 is a foreground local monitor. It writes state to `.ghostfix/daemon.json`, accepts stop requests through `.ghostfix/daemon.stop`, and handles Ctrl+C by updating status before exiting.

The daemon intentionally reuses Watch Mode instead of introducing a second diagnosis path. That keeps parsing, Brain v4 routing, safety policy, and incident recording consistent across `watch` and `daemon start`.

### Local Incident History

Runtime diagnoses are recorded locally in `.ghostfix/incidents.jsonl`. The `ghostfix incidents` command reads that file and can limit output with `--last 10`.

Each incident contains:

- timestamp
- command
- file
- language
- runtime
- error_type
- cause
- fix
- confidence
- auto_fix_available
- resolved_after_fix

Repeated adjacent duplicate incidents are suppressed. This is local debugging history only; it does not retrain Brain v4 and does not relax safety policy.

### Parser And Runtime Detector

After log-event normalization, the parser extracts structured signals from noisy logs:

- Python tracebacks
- Django-style startup/configuration errors
- FastAPI/Uvicorn startup import errors
- Node/npm stack traces and command failures
- missing environment variables
- port conflicts

The runtime detector classifies logs as Python, JavaScript/Node, TypeScript, PHP, or unknown. Supported Python/Django/Flask/FastAPI, Node/Express, Next.js, React, and TypeScript repairs may enter the bounded autonomous sandbox agent; PHP remains limited to legacy simple guarded previews and is not part of the autonomous repair loop.

### Repo-Aware Context

The context engine detects project roots using common Python and Node markers such as `pyproject.toml`, `requirements.txt`, `setup.py`, `manage.py`, `package.json`, `tsconfig.json`, Vite/Next config files, `Dockerfile`, and `docker-compose.yml`.

It collects bounded context from:

- the failing file
- nearby local imports
- framework config files
- dependency files
- safe project config files

It never reads `.env` or secret-named files, skips generated/heavy directories, and enforces max-file and max-character budgets.

### Autonomous Repair Agent

GhostFix v1.0 adds a validation-driven local agent for supported stacks only: Python, Django, Flask, FastAPI, Node/Express, Next.js, React, and TypeScript. The agent can use bounded tools inside a temporary project copy to inspect imports, exports, routes, components, entrypoints, `package.json`, and `tsconfig.json`; rerun build/test/runtime commands; and observe validation output.

The loop is intentionally small:

1. detect the failure
2. build a repo graph
3. generate up to 3 safe candidates
4. validate each candidate in the sandbox
5. rank by validation success, regression score, confidence, repo consistency, and rerun output quality
6. retry at most 3 repair loops
7. stop on regression, duplicate failure, or confidence collapse
8. expose a diff only after validation passes and rollback-capable metadata exists

The agent cannot install packages, edit `.env` or secrets, modify auth/payment/database/deployment/security-sensitive code, or apply a real patch without user approval.

### Production-Like Signal Classification

The event classifier maps explicit user-provided log files to local runtime categories:

- `expected_user_error`
- `app_bug`
- `infrastructure_error`
- `dependency_error`
- `auth_anomaly`
- `repeated_failure`
- `unknown`

It also assigns `info`, `warning`, `error`, or `critical` severity and flags whether Brain escalation is useful. Normal expected user errors, such as a single wrong-password 401, do not request heavy Brain reasoning.

`core/production_signals.py` defines local schemas for runtime, auth, HTTP, session, and error signals. The `integrations/` modules for Sentry, PostHog, and Clarity are disabled-by-default placeholders that normalize local event-shaped objects only. They do not call networks, read API keys, or monitor production systems.

### Memory, Rules, And Retriever

GhostFix prefers deterministic and local evidence before model reasoning:

- Memory can reuse prior successful diagnoses.
- Rules handle known Python and framework patterns.
- The retriever can match local examples when rules are not enough.

These layers are fast and explainable.

### Brain v4 Escalation

Brain v4 is an optional local LoRA reasoning layer. It is guarded and is not called for every error. Deterministic rules, memory, and retrieval get the first chance to answer.

Brain v4 output is advisory:

- It can improve hard or unknown diagnosis.
- It does not bypass safety policy.
- It does not make auto-fix safe by itself.

### Safety And Auto-Fix

The safety policy is the final gate. Auto-fix is limited to deterministic safe allowlists with patch validation, temporary sandbox or project-copy validation, patch preview, user confirmation, backup behavior, and rollback metadata.

Blocked cases include:

- framework configuration changes
- missing packages
- runtime data-shape issues
- non-Python errors
- uncertain or intent-heavy changes

### Reports

GhostFix writes demo and benchmark evidence to `ml/reports`, including:

- demo readiness reports
- runtime Brain v4 reports
- Watch Mode accuracy reports

These reports are useful for README proof, hackathon judging, and regression checks.
