# Limitations

GhostFix is built to be useful and conservative, not magical. These limits are intentional.

## Brain Generation Can Be Slow On CPU

Brain v4 is a local LoRA reasoning layer. On CPU, especially on Windows, generation can be slow. The latest small generate-mode check took 111.337s for 2 files, with 37.740s average Brain generation and a 50% usable Brain output rate.

Use `route-only` mode for public demos and benchmarks when you need to prove escalation logic without CPU-heavy generation.

```powershell
python ml/evaluate_runtime_brain_v4.py --dir tests/brain_escalation_cases --brain-mode route-only
```

Latest verified route-only escalation result: 12 files, Brain activations 12/12, Brain escalations 12/12, 3.435s total runtime, and 58.3% unresolved. That unresolved rate is honest: route-only proves routing, not generated answers.

## Auto-Fix Is Intentionally Limited

GhostFix only auto-fixes narrow deterministic allowlisted cases. Python is the mature path; JS/TS and PHP repairs are tiny guarded patch paths only. Every edit requires patch generation, validation, rollback metadata, and user approval. Model confidence alone does not enable edits.

This means many real errors produce diagnosis and suggested fixes rather than patches. That is by design.

## Non-Python Is Diagnosis-First For Now

JavaScript/Node, TypeScript, npm, and other non-Python runtime logs can be classified and diagnosed. Broad non-Python auto-fix remains disabled; only tiny guarded JS/TS/PHP allowlisted repairs may be previewed and applied.

For non-Python errors, GhostFix provides:

- language/runtime classification
- error type
- likely root cause
- suggested fix
- auto-fix disabled safety reason

## Brain v4 Is Guarded And Not Used For Every Case

Brain v4 is reserved for cases where the deterministic pipeline needs help. If rules, memory, or retrieval produce a strong answer, Brain v4 may be skipped.

This keeps normal debugging fast and makes model reasoning advisory instead of authoritative.

The latest real-world deterministic route-only benchmark used 10 files, activated Brain 0/10 times, and solved 100% deterministically. That is the current reliable MVP path.

## Runtime Debugging Is Evidence-Bound

GhostFix relies on the logs and local code context it can safely inspect. If an error message is vague, truncated, or depends on external services, the diagnosis may correctly fall back to manual review.

## Project Intent Still Matters

Framework configuration, dependency choices, schema changes, and product behavior often require human intent. GhostFix can point to the likely cause, but it avoids changing those areas automatically.
