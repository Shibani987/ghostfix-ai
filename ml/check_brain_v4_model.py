from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.brain_v4_inference import DEFAULT_ADAPTER, full_exception_text, load_config, runtime_config, suppress_brain_v4_noise


LOCAL_BASE_MODEL = Path("ml/models/base_model")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(args.config, args.base_model, args.adapter)
    print_report(report)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check GhostFix Brain v4 base model and LoRA adapter compatibility.")
    parser.add_argument("--config", default="ml/configs/brain_v4_lora_config.yaml", help="Brain v4 runtime config path.")
    parser.add_argument("--base-model", default="", help="Override base model path for this check.")
    parser.add_argument("--adapter", default="", help="Override adapter path for this check.")
    return parser.parse_args(argv)


def build_report(config_path: str | Path, base_model_override: str = "", adapter_override: str = "") -> dict[str, Any]:
    cfg = runtime_config(load_config(config_path), allow_env=True)
    base_path = Path(base_model_override or str(cfg.get("base_model_path") or "")).expanduser()
    adapter_path = Path(adapter_override or str(cfg.get("output_dir") or DEFAULT_ADAPTER)).expanduser()
    adapter_config = _read_json(adapter_path / "adapter_config.json")
    base_config = _read_json(base_path / "config.json")
    local_base_config = _read_json(LOCAL_BASE_MODEL / "config.json")
    tokenizer_files = {
        "tokenizer.json": (base_path / "tokenizer.json").exists(),
        "tokenizer_config.json": (base_path / "tokenizer_config.json").exists(),
        "vocab.json": (base_path / "vocab.json").exists(),
        "merges.txt": (base_path / "merges.txt").exists(),
    }

    peft_loads = False
    load_exception = ""
    if base_path.exists() and adapter_path.exists():
        try:
            peft_loads = _try_peft_load(base_path, adapter_path)
        except Exception as exc:
            load_exception = full_exception_text(exc)

    return {
        "base_model_path": str(base_path),
        "base_model_exists": base_path.exists(),
        "adapter_path": str(adapter_path),
        "adapter_path_exists": adapter_path.exists(),
        "adapter_base_model_name_or_path": adapter_config.get("base_model_name_or_path", ""),
        "adapter_peft_type": adapter_config.get("peft_type", ""),
        "adapter_peft_version": adapter_config.get("peft_version", ""),
        "adapter_target_modules": adapter_config.get("target_modules", []),
        "adapter_rank": adapter_config.get("r"),
        "adapter_lora_alpha": adapter_config.get("lora_alpha"),
        "detected_base_model_type": base_config.get("model_type", ""),
        "detected_architecture": _first(base_config.get("architectures")),
        "detected_hidden_size": base_config.get("hidden_size"),
        "detected_num_hidden_layers": base_config.get("num_hidden_layers"),
        "detected_num_attention_heads": base_config.get("num_attention_heads"),
        "local_packaged_base_model_path": str(LOCAL_BASE_MODEL),
        "local_packaged_base_exists": LOCAL_BASE_MODEL.exists(),
        "local_packaged_hidden_size": local_base_config.get("hidden_size"),
        "local_packaged_model_type": local_base_config.get("model_type", ""),
        "tokenizer_files": tokenizer_files,
        "tokenizer_compatible": any(tokenizer_files.values()),
        "peft_adapter_loads": peft_loads,
        "load_exception": load_exception,
        "recommended_fix": _recommended_fix(
            base_path,
            adapter_path,
            adapter_config,
            base_config,
            local_base_config,
            load_exception,
            peft_loads,
        ),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _try_peft_load(base_path: Path, adapter_path: Path) -> bool:
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    with suppress_brain_v4_noise():
        model = AutoModelForCausalLM.from_pretrained(str(base_path), local_files_only=True)
        PeftModel.from_pretrained(model, str(adapter_path), local_files_only=True)
    return True


def _recommended_fix(
    base_path: Path,
    adapter_path: Path,
    adapter_config: dict[str, Any],
    base_config: dict[str, Any],
    local_base_config: dict[str, Any],
    load_exception: str,
    peft_loads: bool,
) -> str:
    if peft_loads:
        return "Current base model, tokenizer files, and LoRA adapter load successfully."
    if not base_path.exists():
        return f"Set GHOSTFIX_BASE_MODEL_PATH or brain_v4_lora_config.yaml base_model_path to an existing local base model path. Packaged candidate: {LOCAL_BASE_MODEL}."
    if not adapter_path.exists():
        return "Restore or point output_dir to the LoRA adapter directory containing adapter_config.json and adapter weights."
    detected_hidden = base_config.get("hidden_size")
    local_hidden = local_base_config.get("hidden_size")
    if detected_hidden and local_hidden and detected_hidden != local_hidden:
        return (
            f"Use the base model that matches the adapter hidden size. Current base hidden_size={detected_hidden}; "
            f"packaged base hidden_size={local_hidden}. Try setting GHOSTFIX_BASE_MODEL_PATH={LOCAL_BASE_MODEL} "
            "or updating ml/configs/brain_v4_lora_config.yaml to that path."
        )
    if "size mismatch" in load_exception.lower():
        return "Use the exact base model used when the LoRA adapter was trained/exported; the current base architecture does not match adapter tensor shapes."
    adapter_base = adapter_config.get("base_model_name_or_path")
    if adapter_base and not Path(str(adapter_base)).exists():
        return "The adapter references a non-local training path; use a local copy of that exact base model or set GHOSTFIX_BASE_MODEL_PATH to the matching exported base."
    return "Base and adapter metadata look compatible. If PEFT still fails, inspect the exact exception above and installed transformers/peft versions."


def print_report(report: dict[str, Any]) -> None:
    print("GhostFix Brain v4 Compatibility Report")
    print("")
    print(f"base model path exists: {_yes_no(report['base_model_exists'])} ({report['base_model_path']})")
    print(f"adapter path exists: {_yes_no(report['adapter_path_exists'])} ({report['adapter_path']})")
    print(f"adapter base_model_name_or_path: {report['adapter_base_model_name_or_path'] or 'unknown'}")
    print(f"detected base model type: {report['detected_base_model_type'] or 'unknown'}")
    print(f"detected architecture: {report['detected_architecture'] or 'unknown'}")
    print(f"detected hidden size: {report['detected_hidden_size'] or 'unknown'}")
    print(f"adapter target_modules: {report['adapter_target_modules'] or 'unknown'}")
    print(f"adapter PEFT version: {report['adapter_peft_version'] or 'unknown'}")
    print(f"tokenizer compatible: {_yes_no(report['tokenizer_compatible'])} ({_tokenizer_summary(report['tokenizer_files'])})")
    print(f"PEFT adapter loads: {_yes_no(report['peft_adapter_loads'])}")
    if report["load_exception"]:
        print("exact exception:")
        print(report["load_exception"])
    print(f"recommended fix: {report['recommended_fix']}")


def _first(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return value or ""


def _tokenizer_summary(files: dict[str, bool]) -> str:
    present = [name for name, exists in files.items() if exists]
    return ", ".join(present) if present else "no tokenizer files found"


def _yes_no(value: Any) -> str:
    return "yes" if bool(value) else "no"


if __name__ == "__main__":
    raise SystemExit(main())
