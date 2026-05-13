# GhostFix Packaging

GhostFix is packaged as the `ghostfix-ai` Python distribution with the `ghostfix` console command.

## Local Wheel Build

Install the build helper if needed:

```powershell
python -m pip install build
```

Build the source distribution and wheel:

```powershell
python -m build
```

Expected outputs are written to `dist/`:

- `ghostfix_ai-<version>.tar.gz`
- `ghostfix_ai-<version>-py3-none-any.whl`

## Local Install Test

Create a clean virtual environment and install the built wheel:

```powershell
python -m venv .venv-packaging-test
.\.venv-packaging-test\Scripts\Activate.ps1
python -m pip install dist\ghostfix_ai-0.2.0-py3-none-any.whl
ghostfix --version
ghostfix doctor
```

Remove the test environment when finished.

## Editable Install

For local development:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
ghostfix doctor
```

Editable install should expose the same console command as the wheel.

## PyPI Publish Flow

For a future public release:

```powershell
python -m unittest discover tests
python -m cli.main verify-release
python -m cli.main validate-production
python -m cli.main beta-check
python -m build
python -m twine check dist/*
python -m twine upload --repository testpypi dist/*
python -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple ghostfix-ai
ghostfix doctor
```

Only upload to PyPI after the TestPyPI install and smoke tests pass:

```powershell
python -m twine upload dist/*
```

## Version Bump Flow

1. Update `version` in `pyproject.toml`.
2. Update `APP_VERSION` in `cli/main.py`.
3. Update `CHANGELOG.md`.
4. Run tests and validation gates.
5. Build fresh artifacts from a clean tree.

## Uninstall

```powershell
python -m pip uninstall ghostfix-ai
```

## Distribution Hygiene

The base wheel intentionally includes source packages needed for local diagnosis and excludes model/retriever artifacts, local runtime state, reports, caches, backups, databases, and heavy model/checkpoint files.

Retriever dependencies are optional under the `retriever` extra. Brain v4 dependencies are optional under the `brain-v4` extra. Cloud memory dependencies are optional under the `cloud-memory` extra. Local Python diagnosis and deterministic safety gates do not require them.
