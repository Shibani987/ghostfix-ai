# GhostFix AI System Design

## Product Overview

GhostFix AI is a local-first debugging assistant. It runs or watches terminal commands, detects tracebacks and runtime errors, extracts nearby source context, explains the likely root cause, recommends a fix, and applies only small validated allowlisted patches when the safety policy allows it. Python is the mature path; JS/TS and PHP edits remain tiny guarded repair paths.

The problem GhostFix solves is the gap between seeing a terminal traceback and safely making the next code change. It combines deterministic rules, local memory, a TF-IDF retriever, optional local embeddings, optional local LLM reasoning, and classic ML "Brain" models to produce useful guidance without depending on cloud inference.

Key features:

- Run a Python file and analyze stderr tracebacks.
- Watch arbitrary terminal commands for live Python tracebacks.
- Parse error type, message, file, and line number.
- Extract local code context around the failing line.
- Explain root cause and recommended fix.
- Generate patch previews for tightly scoped deterministic cases.
- Require backup, validation, and safety-policy approval before auto-fix.
- Log feedback for future dataset improvement.
- Run Brain v3.3 in experimental or shadow-only modes without replacing Brain v1.

## System Architecture

The runtime path is intentionally simple and conservative:

```text
CLI / watcher
  -> runner / terminal_watcher
  -> parser / root_cause_analyzer
  -> context extraction
  -> decision_engine
  -> safety_policy
  -> patch planner / validator
  -> optional user-approved auto-fix
```

Important modules:

- `cli/main.py` exposes `ghostfix run`, `watch`, `analyze`, `memory`, and daemon commands.
- `core/runner.py` runs Python files, parses stderr, gathers context, requests a decision, builds a patch plan, applies the safety policy, and displays output.
- `agent/terminal_watcher.py` streams command output, detects tracebacks, and runs the same decision/safety flow in watch mode.
- `core/parser.py` and `core/root_cause_analyzer.py` turn raw tracebacks into structured evidence.
- `core/context.py` extracts nearby source lines.
- `core/decision_engine.py` combines memory, rules, retriever, optional local LLM output, and Brain metadata.
- `core/local_llm.py` optionally loads a local Hugging Face code model from `GHOSTFIX_LOCAL_MODEL_PATH` for structured reasoning when fast paths are insufficient.
- `core/autofix.py`, `core/patch_validator.py`, and `core/command_rerunner.py` handle deterministic patch planning, validation, backup, and rerun verification.
- `core/safety_policy.py` is the final gate. It must remain conservative and independent of model confidence alone.

Brain v1 vs Brain v3.3:

- Brain v1 is the stable runtime default.
- Brain v3.3 is experimental opt-in through `GHOSTFIX_BRAIN_V33=1`.
- Brain v3.3 may add metadata such as complexity and auto-fix safety, but it does not replace the safety policy and must never enable auto-fix by itself.
- Shadow mode runs Brain v3.3 beside Brain v1 for comparison without changing decisions.

## ML Pipeline

The ML lifecycle evolved from broad dataset construction into stricter production-oriented validation.

Dataset creation:

- Raw data is collected from local logs, GitHub issues, GitHub pull requests, Stack Overflow, and hand-built manual examples.
- Dataset collector scripts live under `ml/dataset_collectors/`.
- Processed datasets currently live under `ml/processed/`.
- Raw source dumps currently live under `ml/raw/`.

Strict audit:

- `ml/audit_dataset_v2_strict.py` filters the v2 clean dataset into high-quality v3 records.
- It rejects vague fixes, mismatched error/fix pairs, unrelated context, non-traceback messages, weak labels without strong signal, and discussion noise.
- Output includes strict accepted records and rejection reports.

Hard negative mining:

- `ml/hard_negative_mining_v2.py` runs a current Brain model on the strict dataset.
- It identifies high-confidence wrong predictions, complexity confusion, error/fix-template confusion, and unsafe cases predicted safe before guard.
- It creates targeted contrastive examples rather than random synthetic spam.

Calibration and targeted boosts:

- `ml/build_complexity_calibration_set.py` creates targeted examples for complexity confusions.
- `ml/build_unsafe_recall_boost_set.py` adds unsafe contrastive examples for destructive file, database, subprocess, network, config, and environment mutation patterns.
- Calibration focuses on confidence honesty and safety recall, not raw accuracy alone.

Training pipeline evolution:

- Brain v1 uses classic local ML for `error_type` and `fix_template`.
- Brain v2 added separate heads and hard auto-fix safety guards.
- Brain v3/v3.1/v3.2/v3.3 added richer features, stricter datasets, hard negatives, calibration sets, unsafe recall boosts, and production-candidate validation.
- Brain v3.3 remains experimental and opt-in. Brain v1 remains the default.

Feature families used by v3 lineage:

- Error message text.
- Exception class.
- Failing line.
- Surrounding code context.
- Stack trace depth.
- Keyword flags for file, JSON, index, import, subprocess, config, and similar signals.
- TF-IDF features plus structured features.

## Safety System

Safety is deliberately separate from prediction.

`core/safety_policy.py` evaluates:

- Error type.
- Complexity class.
- Confidence.
- Patch availability.
- Patch validation.
- Brain auto-fix safety metadata.

The policy blocks auto-fix unless the case is deterministic, the patch exists, the patch validates, confidence is sufficient, and no model or guard metadata marks it unsafe.

The guard system exists because ML can be confidently wrong. Guards are applied in predictor helpers such as Brain v2/v3.3 to prevent unsafe model output from becoming permissive runtime behavior. Examples:

- `NameError`, `FileNotFoundError`, `KeyError`, and `IndexError` are generally denied because intent or data shape may be required.
- `needs_project_context` and `unsafe_to_autofix` are blocked.
- Destructive file operations, database mutation, subprocess shell commands, and config/environment mutation are treated conservatively.
- Brain-only and local LLM-only predictions never enable auto-fix.

Unsafe auto-fix is blocked because the cost of an incorrect edit can include data loss, broken project state, security exposure, or hiding a real production incident.

## Decision Flow

The decision engine uses layered evidence:

```text
memory
  -> package rule
  -> deterministic rules
  -> retriever
  -> Brain metadata
  -> optional local LLM reasoning fallback
  -> generic fallback
  -> safety policy
```

Memory:

- Reuses successful historical fixes for repeated errors.
- Does not bypass safety.

Rules:

- Provide stable cause/fix explanations for known Python errors.
- Own default auto-fix eligibility for deterministic cases.

Retriever:

- Finds similar local training examples.
- Adds contextual fix guidance.

Brain:

- Adds classification metadata and confidence.
- Can improve diagnosis.
- Cannot independently enable auto-fix.

Local LLM:

- Loads only from `GHOSTFIX_LOCAL_MODEL_PATH` when configured.
- Requires the Hugging Face model files to already exist locally.
- Returns strict JSON with root cause, evidence, suggested fix, confidence, and `safe_to_autofix`.
- Improves broad terminal diagnosis for React/Vite/Next.js, Node, Java, PHP, and unknown errors.
- Cannot independently enable auto-fix.

Fallback:

- If no strong evidence exists, GhostFix gives a conservative review-oriented recommendation.

## Brain Versions

Brain v1:

- Stable runtime default.
- Predicts `error_type` and `fix_template`.
- Uses local classic ML artifacts in `ml/models/ghostfix_brain_v1.pkl`.
- Remains required and must not be removed.

Brain v2:

- Experimental opt-in via `GHOSTFIX_BRAIN_V2=1`.
- Adds multi-head predictions and an auto-fix safety guard.
- Retained for reproducibility and comparison.

Brain v3.3:

- Production-candidate experimental model.
- Opt-in via `GHOSTFIX_BRAIN_V33=1`.
- Loads `ml/models/ghostfix_brain_v33.pkl`.
- Provides `error_type`, `fix_template`, `complexity_class`, `auto_fix_safety`, confidence, and guard metadata.
- Uses compatibility guards for impossible error/fix-template pairings.
- Still cannot enable auto-fix without the runtime safety policy.

## Shadow Mode

Shadow mode runs Brain v3.3 silently beside Brain v1.

Script:

```powershell
$env:GHOSTFIX_SHADOW_V33="1"
python ml\shadow_mode_runner.py
```

Behavior:

- Brain v1 is treated as the used prediction.
- Brain v3.3 is treated as shadow-only metadata.
- Runtime decisions are not modified.
- CLI output is not changed.
- Logs are written to `ml/reports/shadow_mode_log.jsonl`.

Logged fields include:

- v1 vs v3.3 error type.
- v1 vs v3.3 fix template.
- v1 vs v3.3 complexity class.
- v1 vs v3.3 auto-fix safety.
- v1 vs v3.3 confidence.
- Per-head disagreement flags.
- Whether v3.3 is better or worse than v1 against labeled benchmark fields.

Shadow mode exists to gather production-like comparison evidence before promotion. It helps identify regressions without risking runtime behavior.

## Telemetry & Feedback

GhostFix logs local debugging feedback and decisions for future dataset improvement.

Typical logged information:

- Parsed error type and message.
- Local code context.
- Decision metadata.
- Patch attempt status.
- Whether the fix was accepted.
- Whether the rerun succeeded after the fix.

Privacy handling:

- GhostFix is local-first and does not require cloud inference.
- Logs may contain source snippets, file paths, tracebacks, and project names.
- Raw logs should be treated as sensitive development data.
- Before sharing datasets externally, records should be audited, redacted, and filtered for private paths, tokens, credentials, proprietary code, and discussion noise.

## Evaluation Metrics

Primary ML metrics:

- Accuracy by head: `error_type`, `fix_template`, `complexity_class`, and `auto_fix_safety`.
- Per-class precision and recall.
- Confusion matrices, especially for complexity class.
- High-confidence wrong predictions.
- Expected Calibration Error (ECE) or equivalent calibration score.

Safety metrics:

- Unsafe predicted safe before guard.
- Guarded unsafe predicted safe.
- `unsafe_to_autofix` recall.
- Safe precision for auto-fix safety when predicted-safe cases exist.
- Count of impossible error type/fix-template mappings.

Operational metrics:

- Shadow disagreement rate.
- v3.3 better/worse cases versus Brain v1.
- Failure pattern grouping by source and error type.
- Manual review rate.

## Production Readiness Status

Complete:

- Stable Brain v1 runtime default.
- Conservative safety policy.
- Patch validation and backup flow.
- Experimental Brain v3.3 opt-in flag.
- Brain v3.3 shadow mode.
- Strict dataset audit and real-world benchmark cleaning.
- Hard negative, complexity calibration, and unsafe recall boost scripts.
- Production candidate validation report generation.
- Project audit, cleanup plan, and final project report.

Experimental:

- Brain v2 runtime opt-in.
- Brain v3.3 runtime opt-in.
- Shadow-mode monitoring.
- v3 lineage training/evaluation scripts.
- LoRA training scripts.

Current limitations:

- ML scripts are still mostly flat under `ml/`; future reorganization should use compatibility wrappers.
- `ml/raw`, `ml/processed`, and `ml/reports` contain many large historical artifacts and should be governed by retention policy.
- Brain v3.3 is promising but remains opt-in until shadow-mode evidence and production gates are stable over time.
- Some CLI display strings have Windows encoding sensitivity unless UTF-8 output is configured.
- Dataset privacy review is required before sharing logs or training data outside the local machine.

Production posture:

GhostFix is safe to use as a local debugging assistant with Brain v1 as default and conservative auto-fix gates. Brain v3.3 should remain experimental or shadow-only until long-running shadow logs show stable safety, calibration, and regression behavior.
