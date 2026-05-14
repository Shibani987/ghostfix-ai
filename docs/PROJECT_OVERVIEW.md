# Project Overview

GhostFix AI is a debugging assistant for runtime errors. It is designed for the ordinary developer loop: run a script, start a server, watch it fail, and get a clear diagnosis without copying the logs into another tool.

## The Problem

Runtime errors are noisy. A traceback or dev-server log may include many lines, framework internals, repeated messages, and only one small clue that points to the real cause. Beginners can get stuck reading the wrong line. Experienced backend developers lose time switching between terminal output, editor search, docs, and chat prompts.

## The Solution

GhostFix watches the command that failed, extracts the important evidence, and explains the most likely root cause. For a small set of safe validated cases, it can preview and apply a fix after passing safety checks. Python is the mature path; supported Python/Django/Flask/FastAPI, Node/Express, Next.js, React, and TypeScript fixes can use a bounded autonomous sandbox loop with candidate ranking and project validation. PHP remains legacy simple guarded preview support.

The core idea is simple: no prompts, just logs, instant fixes when they are safe.

## How GhostFix Works Internally

1. A command is run through the CLI or watch mode.
2. GhostFix captures stdout and stderr as bounded structured log events.
3. The reliability core buffers partial lines, groups multi-line errors, and protects against malformed or huge logs.
4. Runtime parsers look for tracebacks, stack traces, server startup failures, and known log patterns.
5. The detector identifies language, framework, runtime, error type, file path, and line number when available.
6. Deterministic rules handle common known cases first.
7. Memory and retrieval help with repeated or similar failures.
8. Supported framework patches are tested in a temporary project copy.
9. If validation exposes a new deterministic failure, GhostFix can retry up to two times.
10. Harder unknown cases can route to Brain v4 if it is enabled and available.
11. The final result includes the cause, likely fix, confidence, and whether auto-fix is allowed.

## Why Hybrid Routing Is Used

Not every debugging problem needs a model. Many failures are predictable: missing colons, empty JSON input, missing imports, bad app targets, port conflicts, or missing environment variables. A hybrid router lets GhostFix use the cheapest and safest tool first, then escalate only when needed.

This keeps normal feedback fast while still leaving room for deeper reasoning on unfamiliar failures.

## Why Deterministic Rules Are Faster And Safer

Rules are repeatable. If the same error appears twice, the same rule gives the same answer. That matters for auto-fix because editing code should not depend on a model guess.

Deterministic rules are used first because they are:

- Fast enough for terminal feedback.
- Easy to test.
- Easy to block when the case is unsafe.
- Easier to explain to a new user.
- Safer for simple patch generation.

## Why Brain v4 Is Guarded

Brain v4 is useful for hard cases, but model output is not treated as permission to edit code. It is advisory. GhostFix can use Brain v4 to improve diagnosis, routing, and explanation, but auto-fix still depends on the same safety policy.

Brain v4 is guarded because:

- Models can be wrong or too generic.
- Some errors require project intent.
- Some fixes are destructive or broad.
- Local model files and adapters must be compatible.
- Slow generation should not block common deterministic cases.

## How Watch Mode Works

Watch mode starts a real command such as a Python script, Django-like server, FastAPI app, or Node.js dev server. It streams the process output and scans the text for known runtime error shapes.

Before parsing, the reliability core converts output into log events, buffers partial traceback chunks, bounds large logs, and makes sure malformed unicode or noisy mixed output does not crash GhostFix.

When GhostFix detects an error, it prints a compact diagnosis. With `--verbose`, it also shows routing details, evidence, and Brain telemetry. Watch mode does not apply fixes unless `--fix` is passed, and even then only validated allowlisted fixes are eligible.

## How Auto-Fix Safety Works

Auto-fix is intentionally limited. GhostFix checks the error type, source file, patch plan, and validation result before applying anything. Python patches use AST/compile checks; supported JS/TS framework patches use temporary project-copy validation such as `npm run build` or `tsc --noEmit` when available. A backup is created first using the `*.bak_YYYYMMDD_HHMMSS` pattern.

Auto-fix is blocked for ambiguous cases, broad framework configuration, missing packages, unsafe runtime/data-shape errors, secrets, auth, database, payment, deployment, and any unsupported language/path.

## Multi-Language Support Today

Python is the mature path. GhostFix can diagnose Python tracebacks and common Django, Flask, FastAPI, and Uvicorn failures.

JavaScript, Node.js, React, Next.js, and TypeScript-style dev logs are supported for detection, diagnosis, and guarded allowlisted fixes when validation can prove the patch. The v1 autonomous loop may inspect repo graphs, rank up to 3 candidates, rerun validation, and converge only when regression checks pass. PHP errors are still supported for diagnosis and legacy simple guarded previews.

## Current Product Direction

The current direction is to make GhostFix more useful across longer development sessions: daemon polish, recurring incident summaries, stronger local models, editor integration, broader validated framework fix coverage, CI/CD integration, and observability-style incident reporting.
