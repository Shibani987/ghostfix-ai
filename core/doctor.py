from __future__ import annotations

import importlib.util
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any


REQUIRED_PACKAGES = ("typer", "rich")
OPTIONAL_PACKAGES = ("sklearn", "numpy", "dotenv", "supabase", "django", "flask", "fastapi", "uvicorn", "torch", "transformers", "peft", "accelerate")


def run_doctor(cwd: str | Path = ".") -> list[dict[str, Any]]:
    root = Path(cwd).resolve()
    checks: list[dict[str, Any]] = []

    python_status = "OK" if sys.version_info >= (3, 10) else "FAIL"
    checks.append(_check(
        "Python version",
        python_status,
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} (requires >=3.10)",
    ))
    checks.append(_check("OS", "OK", f"{platform.system()} {platform.release()} ({platform.machine()})"))
    checks.append(_check("Current working directory", "OK", str(root)))
    checks.append(_local_config_check(root))
    checks.append(_memory_mode_check())
    checks.append(_ghostfix_import_check())

    for package in REQUIRED_PACKAGES:
        checks.append(_package_check(package, required=True))

    for package in OPTIONAL_PACKAGES:
        checks.append(_package_check(package))

    checks.append(_path_check("Brain v1 model", root / "ml/models/ghostfix_brain_v1.pkl", "file"))
    checks.append(_path_check("Manual server errors", root / "tests/manual_server_errors", "directory"))
    checks.extend(_brain_v4_checks(root))

    return checks


def _ghostfix_import_check() -> dict[str, Any]:
    try:
        import core.parser  # noqa: F401
        import core.root_cause_analyzer  # noqa: F401
        import core.decision_engine  # noqa: F401
    except Exception as exc:
        return _check("GhostFix imports", "FAIL", str(exc))
    return _check("GhostFix imports", "OK", "core parser/analyzer/decision imports succeeded")


def _package_check(package: str, required: bool = False) -> dict[str, Any]:
    spec = importlib.util.find_spec(package)
    if spec is None:
        label = "Required package" if required else "Optional package"
        status = "FAIL" if required else "WARN"
        return _check(f"{label}: {package}", status, "not installed")
    origin = spec.origin or "installed"
    label = "Required package" if required else "Optional package"
    return _check(f"{label}: {package}", "OK", origin)


def _path_check(name: str, path: Path, kind: str) -> dict[str, Any]:
    exists = path.is_file() if kind == "file" else path.is_dir()
    return _check(name, "OK" if exists else "WARN", str(path) if exists else f"missing: {path}")


def _local_config_check(root: Path) -> dict[str, Any]:
    from core.config import config_path, load_config, validate_config

    path = config_path(root)
    config = load_config(root)
    errors = validate_config(config)
    if errors:
        return _check("GhostFix local config", "FAIL", f"{path}: {'; '.join(errors)}")
    details = f"{path} ({'exists' if path.exists() else 'default in-memory'}; memory_mode={config.get('memory_mode')})"
    return _check("GhostFix local config", "OK", details)


def _memory_mode_check() -> dict[str, Any]:
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"):
        return _check("Memory mode", "OK", "cloud memory configured")
    return _check("Memory mode", "OK", "Running in local-only mode.")


def _brain_v4_checks(root: Path) -> list[dict[str, Any]]:
    base_model = Path(os.environ.get("GHOSTFIX_BASE_MODEL_PATH") or root / "ml/models/base_model")
    adapter = root / "ml/models/ghostfix_brain_v4_lora"
    adapter_config = adapter / "adapter_config.json"
    adapter_weights = adapter / "adapter_model.safetensors"
    base_config = base_model / "config.json"

    checks = [
        _path_check("Brain v4 base model", base_model, "directory"),
        _path_check("Brain v4 adapter directory", adapter, "directory"),
        _path_check("Brain v4 adapter config", adapter_config, "file"),
        _path_check("Brain v4 adapter weights", adapter_weights, "file"),
    ]

    tokenizer_files = [
        adapter / "tokenizer.json",
        adapter / "tokenizer_config.json",
        base_model / "tokenizer.json",
        base_model / "tokenizer_config.json",
    ]
    tokenizer_present = [path.name for path in tokenizer_files if path.exists()]
    checks.append(_check(
        "Brain v4 tokenizer files",
        "OK" if tokenizer_present else "WARN",
        ", ".join(tokenizer_present) if tokenizer_present else "missing tokenizer files",
    ))

    if adapter_config.exists():
        loaded_adapter = _read_json(adapter_config)
        details = (
            f"peft_type={loaded_adapter.get('peft_type', 'unknown')}; "
            f"target_modules={loaded_adapter.get('target_modules', 'unknown')}; "
            f"base={loaded_adapter.get('base_model_name_or_path', 'unknown')}"
        )
        checks.append(_check("Brain v4 adapter metadata", "OK", details))
    else:
        checks.append(_check("Brain v4 adapter metadata", "WARN", "adapter_config.json missing"))

    if base_model.exists() and base_config.exists() and adapter_config.exists() and adapter_weights.exists():
        loaded_base = _read_json(base_config)
        checks.append(_check(
            "Brain v4 adapter compatibility",
            "OK",
            f"base model metadata present: model_type={loaded_base.get('model_type', 'unknown')}, hidden_size={loaded_base.get('hidden_size', 'unknown')}",
        ))
    elif adapter.exists():
        checks.append(_check(
            "Brain v4 adapter compatibility",
            "WARN",
            "adapter is present, but local base model metadata or adapter files are incomplete",
        ))
    else:
        checks.append(_check("Brain v4 adapter compatibility", "WARN", "adapter not available locally"))

    return checks


def _read_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _check(name: str, status: str, details: str) -> dict[str, Any]:
    return {"check": name, "status": status, "details": details}
