# Setup

## Python Setup

GhostFix targets Python 3.10 or newer.

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## Install Dependencies

From PyPI:

```powershell
pip install ghostfix-ai
```

For development or local builds:

```powershell
pip install -e .
```

Run the test suite:

```powershell
python -m unittest discover tests
```

Check the local environment:

```powershell
ghostfix doctor
```

`python -m cli.main doctor` still works from the repository root.

## Local Configuration

GhostFix does not require private Supabase credentials or a `.env` file. Fresh installs run in local-only mode by default.

Create the local config file:

```powershell
ghostfix config init
```

Show the effective config:

```powershell
ghostfix config show
```

The config is stored at:

```text
.ghostfix/config.json
```

Default config:

```json
{
  "memory_mode": "local-only",
  "cloud_memory_enabled": false,
  "brain_v4_enabled": false
}
```

When cloud memory is not configured, the CLI prints:

```text
Running in local-only mode.
```

This is expected and safe. Diagnosis, watch mode, deterministic rules, and safety-gated local auto-fix still work without cloud memory.

## Optional Brain v4 Setup

Brain v4 is optional. The main CLI still works without it.

Install optional ML dependencies when you want local Brain v4 generation:

```powershell
pip install huggingface_hub transformers peft accelerate torch
```

Download the optional local base model:

```powershell
python ml/download_base_model.py
```

Set local paths if needed:

```powershell
$env:GHOSTFIX_BRAIN_V4="1"
$env:GHOSTFIX_BASE_MODEL_PATH="ml/models/base_model"
```

Model weights are intentionally ignored by Git. Keep downloaded base models, checkpoints, and safetensors local.

## Base Model Check

Run:

```powershell
python ml/check_brain_v4_model.py
```

This checks whether the base model path exists, whether the Brain v4 adapter exists, whether tokenizer files are present, and whether the local adapter appears compatible.

## Common Windows PowerShell Commands

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Run a diagnosis:

```powershell
ghostfix run tests/manual_errors/name_error.py
```

Run with verbose routing details:

```powershell
ghostfix run tests/manual_errors/name_error.py --verbose
```

Run a safe auto-fix demo:

```powershell
ghostfix run tests/manual_errors/json_empty_v2.py --fix
```

Run watch mode:

```powershell
ghostfix watch "python demos/python_name_error.py"
```

Set Brain mode for a single shell:

```powershell
$env:GHOSTFIX_BRAIN_MODE="route-only"
```

Clear that setting:

```powershell
Remove-Item Env:\GHOSTFIX_BRAIN_MODE
```

## Troubleshooting

If imports fail, confirm the virtual environment is active and dependencies are installed.

If `ghostfix` is not recognized on Windows after `pip install -e .`, make sure your Python user Scripts directory is on `PATH`, or use `python -m cli.main ...` from the repository root.

If Brain v4 is unavailable, run `python ml/check_brain_v4_model.py` and check the base model and adapter paths.

If watch mode cannot find `npm`, install Node.js or skip the Node demo.

If Django or FastAPI examples are skipped or fail because packages are missing, install the optional framework dependency or use the Python-only demos.

If an auto-fix creates `*.bak_YYYYMMDD_HHMMSS`, that is expected. Backup files are ignored by Git and can be deleted after review.
