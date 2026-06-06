# ghostfix.config.py
# ─────────────────────────────────────────────────────────────────────────────
# Place this file in your project root.
# When present, GhostFix uses your custom/local model — no cloud API key needed.
#
# Run:  ghostfix watch "your command" --fix
# ─────────────────────────────────────────────────────────────────────────────

GHOSTFIX_CONFIG = {
    "model": {
        "type": "custom",

        # ── Option A: Ollama (local) ──────────────────────────────────────
        # Install Ollama: https://ollama.com
        # Pull a model:   ollama pull codellama:13b
        #                 ollama pull deepseek-coder:6.7b
        "endpoint": "http://localhost:11434/api/chat",
        "model_name": "codellama:13b",

        # ── Option B: OpenAI-compatible server (LM Studio, vLLM, etc.) ───
        # "endpoint": "http://localhost:1234",        # LM Studio default
        # "model_name": "local-model",
        #
        # ── Option C: Your own remote model server ────────────────────────
        # "endpoint": "http://192.168.1.100:8000",
        # "model_name": "my-finetuned-coder",
        # "api_key": "optional-bearer-token",
        # "headers": {"X-Team": "dev"},

        "timeout_seconds": 120,
    },

    "watch": {
        # Paths to ignore when searching for context files
        "ignore": [
            "node_modules", ".git", "dist", "__pycache__",
            "venv", ".venv", "env", "migrations",
            ".mypy_cache", ".pytest_cache", "build",
        ],
        "max_file_size_kb": 500,   # skip files larger than this
        "context_lines": 60,       # lines around error to include
    },

    "fix": {
        "auto_apply": False,       # True = apply patch without asking
        "create_backup": True,     # save backup to .ghostfix_backups/
        "restart_on_fix": True,    # restart the watched command after fix
        "max_retries": 3,          # max times to attempt fixing same error
    },

    "ui": {
        "language": "english",
        "show_diff": True,
        "color_theme": "dark",
    },
}
