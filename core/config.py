from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONFIG_DIR = ".ghostfix"
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "memory_mode": "local-only",
    "cloud_memory_enabled": False,
    "brain_v4_enabled": False,
    "brain_mode": "off",
    "auto_fix_default": False,
    "telemetry_enabled": False,
    "export_enabled": False,
}
ALLOWED_MEMORY_MODES = {"local-only", "cloud"}
ALLOWED_BRAIN_MODES = {"off", "route-only", "generate"}


def config_path(cwd: str | Path = ".") -> Path:
    return Path(cwd).resolve() / CONFIG_DIR / CONFIG_FILE


def default_config() -> dict[str, Any]:
    return dict(DEFAULT_CONFIG)


def load_config(cwd: str | Path = ".") -> dict[str, Any]:
    path = config_path(cwd)
    if not path.exists():
        return default_config()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default_config()
    if not isinstance(loaded, dict):
        return default_config()
    merged = default_config()
    merged.update(loaded)
    return merged


def validate_config(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if config.get("memory_mode") not in ALLOWED_MEMORY_MODES:
        errors.append("memory_mode must be one of: local-only, cloud")
    if not isinstance(config.get("cloud_memory_enabled"), bool):
        errors.append("cloud_memory_enabled must be true or false")
    if not isinstance(config.get("brain_v4_enabled"), bool):
        errors.append("brain_v4_enabled must be true or false")
    if config.get("brain_mode") not in ALLOWED_BRAIN_MODES:
        errors.append("brain_mode must be one of: off, route-only, generate")
    if not isinstance(config.get("auto_fix_default"), bool):
        errors.append("auto_fix_default must be true or false")
    if not isinstance(config.get("telemetry_enabled"), bool):
        errors.append("telemetry_enabled must be true or false")
    if not isinstance(config.get("export_enabled"), bool):
        errors.append("export_enabled must be true or false")
    if config.get("telemetry_enabled") is True:
        errors.append("telemetry_enabled cannot be enabled; GhostFix has no default cloud telemetry path")
    return errors


def init_config(cwd: str | Path = ".", overwrite: bool = False) -> tuple[Path, bool]:
    path = config_path(cwd)
    if path.exists() and not overwrite:
        return path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(default_config(), indent=2) + "\n", encoding="utf-8")
    return path, True


def is_local_only_mode(cwd: str | Path = ".") -> bool:
    config = load_config(cwd)
    return config.get("memory_mode") == "local-only" or not bool(config.get("cloud_memory_enabled"))
