# Configuration

GhostFix merges configuration from two places:

1. Global config: `~/.ghostfix/config.json`
2. Project config: `ghostfix.config.py` in the current directory, or a path passed with `--config`

Project config overrides global config.

## Create Project Config

```bash
ghostfix init
```

This creates `ghostfix.config.py`.

## Full Example

```python
GHOSTFIX_CONFIG = {
    "model": {
        "type": "custom",
        "endpoint": "http://localhost:11434/api/chat",
        "model_name": "codellama:13b",
        "timeout_seconds": 120,
    },
    "watch": {
        "ignore": [
            "node_modules", ".git", "dist", "__pycache__",
            "venv", ".venv", "env", "migrations",
            ".mypy_cache", ".pytest_cache", "build",
        ],
        "max_file_size_kb": 500,
        "context_lines": 60,
    },
    "fix": {
        "auto_apply": False,
        "create_backup": True,
        "restart_on_fix": True,
        "max_retries": 3,
    },
    "ui": {
        "language": "english",
        "show_diff": True,
        "color_theme": "dark",
    },
}
```

## Model

| Key | Description |
| --- | --- |
| `type` | Use `custom` for local/custom endpoints. |
| `endpoint` | Ollama `/api/chat` URL or OpenAI-compatible base URL. |
| `model_name` | Model sent to the endpoint. |
| `api_key` | Optional bearer token for custom endpoints. |
| `headers` | Optional extra HTTP headers. |
| `timeout_seconds` | Request timeout. Defaults to `120`. |

Cloud providers use `--ai` instead of the `model` block.

## Watch

| Key | Default | Description |
| --- | --- | --- |
| `ignore` | Common generated folders | Paths skipped during context search. |
| `max_file_size_kb` | `500` | Files larger than this are skipped. |
| `context_lines` | `60` | Lines around the detected error line. |

## Fix

| Key | Default | Description |
| --- | --- | --- |
| `auto_apply` | `False` | Apply patches without asking. |
| `create_backup` | `True` | Copy changed files into `.ghostfix_backups/`. |
| `restart_on_fix` | `True` | Restart the watched command after a successful patch. |
| `max_retries` | `3` | Stop trying after the same error repeats. |

## Cloud Prompt Behavior

`ghostfix watch "CMD" --fix --ai` asks for provider and API key on every run.

`ghostfix watch "CMD" --fix --ai --provider gemini` skips provider selection but still asks for the API key.

`ghostfix setup` can save a global default provider/key for setup workflows, but `watch --ai` does not silently reuse it.
