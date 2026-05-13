# GhostFix Training Data Export

GhostFix can create a local, user-reviewed export from your own incidents, feedback, and auto-fix audit history.

```powershell
ghostfix stats
ghostfix export-training-data
ghostfix export-training-data --include-snippets
```

## What Gets Exported

Exports are written to `.ghostfix/exports/ghostfix_training_export_<timestamp>.jsonl`.

Each row contains only fields useful for future local model and retriever improvement:

- `error_type`
- `framework`
- `runtime`
- `language`
- `likely_cause`
- `suggested_fix`
- `confidence`
- `auto_fix_available`
- `rollback_available`
- `resolved_after_fix`
- `feedback_rating`
- `feedback_note`
- `validator_result`

With `--include-snippets`, GhostFix adds a short sanitized `snippet` field when snippet-like data exists. Snippets may contain project code, so review the file before sharing.

## Redaction

GhostFix redacts common sensitive or identifying data before writing export rows:

- usernames in Windows, macOS, and Linux home paths
- absolute local paths
- email addresses
- API keys, tokens, passwords, secrets, and long token-like strings
- `.env`-style values
- long raw code blocks

Redaction is a safety layer, not a substitute for review. Always inspect the exported JSONL before sending it to another person.

## No Automatic Uploads

`ghostfix export-training-data` only writes a local file. It does not upload data, call a cloud API, or send telemetry.

The command always prints:

```text
Export created locally.
No data was uploaded.
Review before sharing.
```

## Why This Helps

Closed-beta feedback becomes useful when incidents are paired with user ratings and audit outcomes. These local exports can later help improve retrieval rules, evaluation fixtures, and future local models without requiring automatic telemetry.

Users decide whether to share an export manually. GhostFix does not send it automatically.
