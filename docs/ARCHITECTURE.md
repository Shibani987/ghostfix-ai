# Architecture

GhostFix is a small pipeline-oriented CLI.

## Modules

```text
ghostfix/
  cli.py                    command entry points
  config/manager.py         global and project config loading
  core/watcher.py           process runner and repair loop
  core/error_parser.py      language/error/file/line extraction
  core/context_builder.py   code context and project tree builder
  core/patcher.py           unified diff application and backups
  ai/router.py              prompt building and provider dispatch
  ai/*_provider.py          OpenAI, Claude, Gemini, custom endpoints
  ui/renderer.py            Rich terminal output
```

## Runtime Flow

1. `cli.py` loads config and starts `ProcessWatcher`.
2. `ProcessWatcher` runs the watched command with merged stdout/stderr.
3. Each output line is passed to `ErrorParser.is_error_signal`.
4. Error blocks are parsed into `ParsedError`.
5. `ContextBuilder` resolves the primary file and related stack trace files.
6. `AIRouter` builds a debugging prompt and calls the configured provider.
7. The provider returns JSON with root cause, explanation, suggestion, and patch.
8. `Renderer` shows the result.
9. `Patcher` creates backups, applies the unified diff, and returns status.
10. The watcher restarts the command if configured.

## Patch Strategy

`Patcher` tries:

1. `git apply --whitespace=nowarn -`
2. A minimal manual unified-diff fallback for simple single-file patches

Backups are stored under:

```text
.ghostfix_backups/<timestamp>/
```

## Error Parsing

GhostFix recognizes common signals from:

- Python
- Node.js and TypeScript
- Java
- Go
- Rust
- Ruby
- Generic CLI output

The parser chooses the most specific user file from the stack trace, then sends that location to the context builder.

## AI Response Contract

Providers must return content that can be parsed as JSON:

```json
{
  "root_cause": "why the error happened",
  "explanation": "deeper details",
  "fix_suggestion": "what should change",
  "patch": "--- a/file.py\n+++ b/file.py\n@@ ...",
  "confidence": 0.75,
  "related_files": ["optional.py"]
}
```

If no code patch is appropriate, `patch` should be an empty string and `fix_suggestion` should explain the required command or manual action.
