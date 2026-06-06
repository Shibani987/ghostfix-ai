# Installation

GhostFix is a Python CLI package.

## Requirements

- Python 3.9 or newer
- `pip`
- Git, recommended for reliable patch application
- An AI provider key, or a local/custom model endpoint

## Install From PyPI

```bash
pip install ghostfix
```

Verify:

```bash
ghostfix --help
```

## Install From Source

```bash
git clone https://github.com/Shibani987/ghostfix-ai.git
cd ghostfix-ai
python -m pip install -e .
```

For development:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

## Windows Notes

PowerShell works well:

```powershell
ghostfix watch "npm run dev" --fix --ai
```

If the command itself needs quotes, wrap the full watched command in double quotes and keep inner arguments simple.

## Uninstall

```bash
pip uninstall ghostfix
```

Global provider config, if created, lives at:

```text
~/.ghostfix/config.json
```
