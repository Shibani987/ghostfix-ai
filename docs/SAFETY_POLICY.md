# Safety Policy

GhostFix auto-fix is deliberately conservative. The safety policy is the final gate and is not bypassed by rules, retrievers, Brain predictions, local LLM predictions, or confidence alone.

## When Auto-Fix Is Allowed

Auto-fix is allowed only for small deterministic allowlisted cases when all of these are true:

- The error type is allowlisted.
- The case is classified as deterministic and safe.
- Confidence meets the strict threshold.
- A deterministic patch is available.
- Patch validation passes.
- The user confirms the change, unless an explicit auto-approve mode is used.

Current safe examples include:

- Simple Python missing-colon SyntaxError patches
- Simple JSONDecodeError empty-input guards
- Tiny JS/TS one-line repairs from the deterministic JS/TS allowlist
- Selected JS/TS framework patches that pass temporary project-copy validation
- Simple PHP missing-semicolon repairs from the deterministic PHP allowlist

## When Auto-Fix Is Blocked

Auto-fix is blocked for:

- Errors requiring project intent
- Framework configuration errors
- Missing packages/dependencies
- Data-shape or runtime logic issues
- Low-confidence cases
- Invalid or unavailable patches
- Unsafe Brain metadata
- Local LLM-only diagnoses
- JavaScript, TypeScript, and PHP outside the explicit guarded allowlists
- Any error type outside the auto-fix allowlist

Examples:

- Django `INSTALLED_APPS` issues
- Flask missing templates
- FastAPI/Uvicorn import target problems
- Permission errors
- NameError or KeyError cases that may require intent

## Why Broad JavaScript And PHP Auto-Fix Are Disabled

JavaScript and TypeScript are diagnosis-first with guarded validated allowlists and a bounded autonomous sandbox agent for supported safe cases. PHP is diagnosis-first only with legacy tiny deterministic previews. GhostFix can parse and explain common runtime errors, but edits are limited to explicit allowlists with patch preview, confirmation, rollback metadata, and sandbox validation.

Reasons:

- The mature validation and backup flow is Python-focused.
- JS/PHP package managers, module systems, and project layouts vary widely.
- Safer language-specific patch validation has not been implemented yet.
- Public demo behavior should prefer trustworthy diagnosis over risky edits.

## Backup And Validation Behavior

For allowed Python patches:

- GhostFix generates a patch preview.
- The user is asked before applying the patch.
- A backup file is created before editing.
- The changed Python file is validated.
- GhostFix can rerun the original command to verify the result.

If validation fails, the patch is not applied.

## Model Confidence Is Not Permission

Brain predictions, retriever matches, and optional local LLM output can improve diagnosis, but they do not grant edit permission. The safety policy remains the final authority.

## Local LLM Behavior

GhostFix can optionally use a local Hugging Face code model as a reasoning layer when deterministic rules and retriever matches are insufficient.

Configuration:

```powershell
$env:GHOSTFIX_LOCAL_MODEL_PATH="C:\models\Qwen2.5-Coder-1.5B-Instruct"
```

The model must already exist on disk. GhostFix does not download models at runtime and does not call cloud inference APIs. If the model path or dependency is missing, diagnosis continues through the existing local pipeline.

Local LLM output is expected as structured JSON and is treated as advisory. Even if a local model emits `safe_to_autofix: true`, GhostFix does not allow that field to enable edits.
