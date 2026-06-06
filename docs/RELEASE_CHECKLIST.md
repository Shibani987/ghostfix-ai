# Release Checklist

Use this before publishing a GhostFix release.

## Code

- Run tests:

```bash
python -m pytest
```

- Confirm the CLI starts:

```bash
ghostfix --help
ghostfix watch "python --version"
```

- Check package metadata:

```bash
python -m build
```

## Documentation

- Update `README.md`.
- Update `CHANGELOG.md`.
- Confirm `docs/assets/ghostfix-demo.gif` renders in the README.
- Confirm install commands match the package name.
- Confirm provider behavior is documented.
- Confirm security notes mention AI context sharing.

## Versioning

- Update `pyproject.toml` version.
- Update `ghostfix/__init__.py` if it contains version metadata.
- Add release notes under the matching `CHANGELOG.md` version.

## Packaging

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*
```

Publish to TestPyPI first:

```bash
python -m twine upload --repository testpypi dist/*
```

Then publish to PyPI:

```bash
python -m twine upload dist/*
```

## Smoke Test

In a clean environment:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install ghostfix
ghostfix --help
```

Run one cloud-provider smoke test and one custom-model smoke test if available.
