# GhostFix Watch Mode Reliability

GhostFix watch mode is designed for noisy, long-running local developer
workflows. It should diagnose useful failures without flooding the terminal,
growing memory without bound, or writing duplicate incident history.

## Noisy Logs

Watch mode reads combined subprocess output and tolerates ordinary server noise:
health checks, reload messages, build logs, browser errors, npm warnings, and
mixed stdout/stderr lines. The parser searches for structured runtime failures
inside that noise instead of assuming the entire output is one traceback.

## Duplicate Suppression

Identical traceback blocks are fingerprinted after normalizing volatile details
such as absolute file prefixes and memory addresses. During one watch run,
GhostFix diagnoses a repeated traceback once. Incident history also suppresses a
new row when the latest incident has the same stable fingerprint.

## Streaming Safety

Streaming input is processed through bounded chunks:

- partial lines are buffered and merged safely when later chunks arrive
- incomplete tracebacks flush safely at process end or timeout
- malformed bytes are decoded with replacement characters
- traceback capture is capped so an endless stack cannot consume memory forever

## Bounded Memory Behavior

Watch mode keeps only a bounded recent log buffer for fallback parsing. It also
keeps a bounded cache of traceback fingerprints, so long-running sessions do not
retain every historical crash forever.

Current lightweight limits:

- recent stream buffer: 128 KB
- individual stream event: 32 KB
- traceback capture: 64 KB
- partial line buffer: 16 KB
- handled traceback key cache: 256 entries

These limits are intentionally conservative for local CLI usage.

## Windows Unicode Safety

GhostFix writes watched output using the active terminal encoding with
replacement for characters the terminal cannot represent. Unicode logs should
not crash watch mode on Windows terminals with legacy encodings.

## Incident Flood Protection

Repeated crashes should not infinitely flood `.ghostfix/incidents.jsonl`.
Identical incidents are suppressed at write time, and repeated identical
tracebacks are suppressed before diagnosis during a watch run. Rapid daemon
restarts that hit the same crash repeatedly should leave one incident row for
that stable failure.

## Non-Goals

Reliability hardening does not expand auto-fix safety, enable cloud behavior, or
change Brain/model routing. Watch mode remains a local diagnostic loop; bounded
autonomous repair can only produce a validated diff for supported safe cases and
still requires the explicit safe auto-fix flow and user confirmation before any
real file is edited.
