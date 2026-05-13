from __future__ import annotations

import json
import os
import traceback
import time
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = Path("ml/configs/brain_v4_lora_config.yaml")
DEFAULT_ADAPTER = Path("ml/models/ghostfix_brain_v4_lora")
BASE_MODEL_ENV = "GHOSTFIX_BASE_MODEL_PATH"
BRAIN_DEBUG_ENV = "GHOSTFIX_BRAIN_DEBUG"
BRAIN_MAX_NEW_TOKENS_ENV = "GHOSTFIX_BRAIN_MAX_NEW_TOKENS"
DEFAULT_MAX_NEW_TOKENS = 192
TRAINING_SYSTEM_PROMPT = "You are GhostFix Brain v4. Return ONLY valid JSON. No explanation."
TRAINING_SCHEMA_SYSTEM_PROMPT = (
    "You are GhostFix Brain v4.\n"
    "You MUST return ONLY valid JSON.\n"
    "You MUST use EXACT keys:\n"
    "language, framework, error_type, root_cause,\n"
    "likely_root_cause, evidence, suggested_fix,\n"
    "confidence, safe_to_autofix.\n"
    "Do NOT use any other keys."
)
BRAIN_V4_SCHEMA_KEYS = (
    "language",
    "framework",
    "error_type",
    "root_cause",
    "likely_root_cause",
    "evidence",
    "suggested_fix",
    "confidence",
    "safe_to_autofix",
)


@dataclass
class BrainV4Status:
    available: bool
    reason: str = ""


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        return {}
    try:
        import yaml

        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return _parse_minimal_yaml(config_path.read_text(encoding="utf-8"))


def runtime_config(config: dict[str, Any] | None = None, *, allow_env: bool = True) -> dict[str, Any]:
    cfg = dict(config or {})
    env_base_model = os.getenv(BASE_MODEL_ENV)
    if allow_env and env_base_model:
        cfg["base_model_path"] = env_base_model
    cfg.setdefault("output_dir", str(DEFAULT_ADAPTER))
    return cfg


def adapter_available(config: dict[str, Any] | None = None) -> bool:
    cfg = runtime_config(config)
    output_dir = Path(str(cfg.get("output_dir") or DEFAULT_ADAPTER)).expanduser()
    return output_dir.exists() and any(output_dir.iterdir())


def check_inference_ready(config: dict[str, Any] | None = None) -> BrainV4Status:
    cfg = runtime_config(config or load_config(), allow_env=config is None)
    base_model_value = str(cfg.get("base_model_path") or "").strip()
    if not base_model_value:
        return BrainV4Status(False, f"Base model path is not configured; set {BASE_MODEL_ENV}.")
    base_path = Path(base_model_value).expanduser()
    adapter_path = Path(str(cfg.get("output_dir") or DEFAULT_ADAPTER)).expanduser()
    if not base_path.exists():
        return BrainV4Status(False, f"Base model path does not exist: {base_path}")
    if not adapter_path.exists():
        return BrainV4Status(False, f"LoRA adapter path does not exist: {adapter_path}")
    try:
        import transformers  # noqa: F401
        import peft  # noqa: F401
        import torch  # noqa: F401
    except Exception as exc:
        return BrainV4Status(False, f"Missing inference dependency: {exc}")
    return BrainV4Status(True, "Brain v4 adapter is available.")


def full_exception_text(exc: BaseException) -> str:
    return "".join(traceback.format_exception_only(type(exc), exc)).strip()


class BrainV4Inference:
    def __init__(self, config_path: str | Path = DEFAULT_CONFIG):
        self.config_path = Path(config_path)
        allow_env = self.config_path == DEFAULT_CONFIG
        self.config = runtime_config(load_config(config_path), allow_env=allow_env)
        self.model = None
        self.tokenizer = None
        self.reason = ""
        self._load_attempted = False
        self._final_debug_count = 0

    def load(self) -> BrainV4Status:
        self._load_attempted = True
        status = check_inference_ready(self.config)
        if not status.available:
            self.reason = status.reason
            return status
        try:
            with suppress_brain_v4_noise():
                import torch
                from peft import PeftModel
                from transformers import AutoModelForCausalLM, AutoTokenizer

                self.config = runtime_config(self.config, allow_env=self.config_path == DEFAULT_CONFIG)
                base_path = Path(str(self.config["base_model_path"])).expanduser()
                adapter_path = Path(str(self.config.get("output_dir") or DEFAULT_ADAPTER)).expanduser()
                dtype = torch.float16 if torch.cuda.is_available() else torch.float32
                self.tokenizer = AutoTokenizer.from_pretrained(
                    str(base_path),
                    local_files_only=True,
                    trust_remote_code=True,
                )
                base_model = AutoModelForCausalLM.from_pretrained(
                    str(base_path),
                    local_files_only=True,
                    trust_remote_code=True,
                    torch_dtype=dtype,
                    device_map="auto" if torch.cuda.is_available() else None,
                )
                self.model = PeftModel.from_pretrained(base_model, str(adapter_path), local_files_only=True)
            self.model.eval()
            return BrainV4Status(True, "Brain v4 adapter loaded.")
        except Exception as exc:
            self.reason = f"Brain v4 load failed: {full_exception_text(exc)}"
            self.model = None
            self.tokenizer = None
            return BrainV4Status(False, self.reason)

    def diagnose(
        self,
        *,
        terminal_error: str,
        context: str = "",
        language: str = "unknown",
        framework: str = "unknown",
        parsed_error: dict[str, Any] | None = None,
        max_new_tokens: int | None = None,
        include_debug: bool = False,
    ) -> dict[str, Any]:
        response: dict[str, Any]
        if self.model is None or self.tokenizer is None:
            if self._load_attempted:
                response = {"available": False, "reason": self.reason or "Brain v4 is not loaded."}
            else:
                status = self.load()
                if not status.available:
                    response = {"available": False, "reason": status.reason}
                else:
                    response = self._diagnose_loaded(
                        terminal_error=terminal_error,
                        context=context,
                        language=language,
                        framework=framework,
                        parsed_error=parsed_error,
                        max_new_tokens=_runtime_max_new_tokens(max_new_tokens),
                        include_debug=include_debug,
                    )
        else:
            response = self._diagnose_loaded(
                terminal_error=terminal_error,
                context=context,
                language=language,
                framework=framework,
                parsed_error=parsed_error,
                max_new_tokens=_runtime_max_new_tokens(max_new_tokens),
                include_debug=include_debug,
            )
        return response

    def reload(self) -> BrainV4Status:
        self.model = None
        self.tokenizer = None
        self.reason = ""
        self._load_attempted = False
        return self.load()

    def _diagnose_loaded(
        self,
        *,
        terminal_error: str,
        context: str,
        language: str,
        framework: str,
        parsed_error: dict[str, Any] | None,
        max_new_tokens: int,
        include_debug: bool,
    ) -> dict[str, Any]:
        try:
            user_content = build_runtime_brain_v4_user_content(
                language=language,
                framework=framework,
                terminal_error=terminal_error,
                parsed_error=parsed_error or {},
                code_context=context,
            )
            prompt = render_brain_v4_chat_prompt(self.tokenizer, user_content)
            inputs = self.tokenizer(prompt, return_tensors="pt")
            try:
                model_device = next(self.model.parameters()).device
                inputs = {key: value.to(model_device) for key, value in inputs.items()}
            except Exception:
                pass
            generation_kwargs = build_generation_kwargs(
                inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=getattr(self.tokenizer, "eos_token_id", None),
                eos_token_id=getattr(self.tokenizer, "eos_token_id", None),
            )
            generation_started = time.perf_counter()
            with suppress_brain_v4_noise():
                output_ids = self.model.generate(**generation_kwargs)
            generation_seconds = round(time.perf_counter() - generation_started, 3)
            prompt_length = inputs["input_ids"].shape[-1]
            raw_output = self.tokenizer.decode(output_ids[0][prompt_length:], skip_special_tokens=True)
            json_candidate = extract_json_candidate(raw_output)
            parsed_output = parse_brain_v4_raw_json(raw_output) or {}
            result = finalize_brain_v4_output(parsed_output, input_text=user_content)
            if brain_v4_debug_enabled() and self._final_debug_count < 3:
                print("RAW GENERATED CONTINUATION:", raw_output)
                print("PARSED JSON CANDIDATE:", json_candidate)
                print("FINAL OUTPUT:", result)
                self._final_debug_count += 1
            response = {"available": True, "diagnosis": result, "generation_seconds": generation_seconds}
            if include_debug:
                response["prompt"] = prompt
                response["raw_output"] = raw_output
                response["parsed_output"] = parsed_output
                response["final_output"] = result
        except Exception as exc:
            response = {"available": False, "reason": f"Brain v4 inference failed: {exc}"}
        return response


def _runtime_max_new_tokens(value: int | None = None) -> int:
    if value is not None:
        return max(1, int(value))
    raw = os.getenv(BRAIN_MAX_NEW_TOKENS_ENV, "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            return DEFAULT_MAX_NEW_TOKENS
    return DEFAULT_MAX_NEW_TOKENS


def diagnose(
    terminal_error: str,
    context: str = "",
    language: str = "unknown",
    framework: str = "unknown",
    config_path: str | Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    runner = BrainV4Inference(config_path)
    return runner.diagnose(
        terminal_error=terminal_error,
        context=context,
        language=language,
        framework=framework,
    )


def brain_v4_debug_enabled() -> bool:
    return os.getenv(BRAIN_DEBUG_ENV) == "1"


@contextmanager
def suppress_brain_v4_noise():
    if brain_v4_debug_enabled():
        yield
        return

    old_transformers_verbosity = None
    old_peft_verbosity = None
    transformers_logging = None
    peft_logging = None
    progress_disabled = False
    try:
        try:
            from transformers.utils import logging as transformers_logging

            old_transformers_verbosity = transformers_logging.get_verbosity()
            transformers_logging.set_verbosity_error()
            transformers_logging.disable_progress_bar()
            progress_disabled = True
        except Exception:
            pass
        try:
            from peft.utils import logging as peft_logging

            old_peft_verbosity = peft_logging.get_verbosity()
            peft_logging.set_verbosity_error()
        except Exception:
            pass
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", module=r"transformers(\.|$)")
            warnings.filterwarnings("ignore", module=r"peft(\.|$)")
            warnings.filterwarnings("ignore", message=r".*temperature.*do_sample.*")
            warnings.filterwarnings("ignore", message=r".*top_p.*do_sample.*")
            warnings.filterwarnings("ignore", message=r".*top_k.*do_sample.*")
            yield
    finally:
        if transformers_logging is not None and old_transformers_verbosity is not None:
            try:
                transformers_logging.set_verbosity(old_transformers_verbosity)
                if progress_disabled:
                    transformers_logging.enable_progress_bar()
            except Exception:
                pass
        if peft_logging is not None and old_peft_verbosity is not None:
            try:
                peft_logging.set_verbosity(old_peft_verbosity)
            except Exception:
                pass


def build_generation_kwargs(
    inputs: dict[str, Any],
    *,
    max_new_tokens: int,
    do_sample: bool = False,
    pad_token_id: int | None = None,
    eos_token_id: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    kwargs = {
        **inputs,
        "max_new_tokens": max_new_tokens,
        "do_sample": do_sample,
        "pad_token_id": pad_token_id,
    }
    if eos_token_id is not None:
        kwargs["eos_token_id"] = eos_token_id
    if do_sample:
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if top_k is not None:
            kwargs["top_k"] = top_k
    return kwargs


def parse_brain_v4_output(text: str) -> dict[str, Any] | None:
    raw = parse_brain_v4_raw_json(text)
    if raw is None:
        return None
    return clean_brain_v4_schema(raw)


def parse_brain_v4_raw_json(text: str) -> dict[str, Any] | None:
    candidate = extract_json_candidate(text)
    if not candidate:
        return None
    try:
        raw = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def has_exact_brain_v4_schema(value: Any) -> bool:
    if not isinstance(value, dict) or tuple(value.keys()) and set(value) != set(BRAIN_V4_SCHEMA_KEYS):
        return False
    if set(value) != set(BRAIN_V4_SCHEMA_KEYS):
        return False
    string_keys = ("language", "framework", "error_type", "root_cause", "likely_root_cause", "suggested_fix")
    if any(not isinstance(value.get(key), str) for key in string_keys):
        return False
    evidence = value.get("evidence")
    if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
        return False
    if not isinstance(value.get("confidence"), int) or not 0 <= value["confidence"] <= 100:
        return False
    if not isinstance(value.get("safe_to_autofix"), bool):
        return False
    return True


def clean_brain_v4_schema(value: dict[str, Any]) -> dict[str, Any]:
    repaired = repair_brain_v4_schema(value)
    return finalize_brain_v4_output(repaired)


def finalize_brain_v4_output(parsed: dict[str, Any] | None, *, input_text: str = "") -> dict[str, Any]:
    parsed = parsed or {}
    allowed_keys = set(BRAIN_V4_SCHEMA_KEYS)
    final: dict[str, Any] = {}
    for key in allowed_keys:
        final[key] = parsed.get(key)
    if final.get("error_type") is None:
        final["error_type"] = parsed.get("error_type_hint")
    if final.get("error_type") is None:
        final["error_type"] = _infer_error_type_from_text(input_text)
    if final.get("suggested_fix") is None:
        final["suggested_fix"] = parsed.get("fix") or parsed.get("suggested_solution")
    if final.get("root_cause") is None:
        final["root_cause"] = parsed.get("cause") or parsed.get("diagnosis")
    if final.get("likely_root_cause") is None:
        final["likely_root_cause"] = parsed.get("explanation") or parsed.get("likely_cause")
    evidence_sources = _collect_evidence_sources(parsed)
    if final.get("evidence") is None and evidence_sources:
        final["evidence"] = evidence_sources
    defaults: dict[str, Any] = {
        "language": "unknown",
        "framework": "unknown",
        "error_type": "UnknownError",
        "root_cause": "unknown",
        "likely_root_cause": "unknown",
        "evidence": [],
        "suggested_fix": "",
        "confidence": 50,
        "safe_to_autofix": False,
    }
    for key, default in defaults.items():
        if final.get(key) is None:
            final[key] = default
    final["language"] = _string_value(final.get("language"), "unknown")
    final["framework"] = _string_value(final.get("framework"), "unknown")
    final["error_type"] = _string_value(final.get("error_type"), "UnknownError")
    final["root_cause"] = _string_value(final.get("root_cause"), "unknown")
    final["likely_root_cause"] = _string_value(final.get("likely_root_cause"), final["root_cause"])
    if final["likely_root_cause"] == "unknown" and final["root_cause"] != "unknown":
        final["likely_root_cause"] = final["root_cause"]
    final["suggested_fix"] = str(final.get("suggested_fix") or "")
    if not final["suggested_fix"]:
        final["suggested_fix"] = "Review the error and code context before changing code."
    final["evidence"] = _evidence_value(final.get("evidence"), allow_empty=True)
    final["confidence"] = _confidence_value(final.get("confidence"), default=50)
    final["safe_to_autofix"] = bool(final.get("safe_to_autofix"))
    return {key: final[key] for key in BRAIN_V4_SCHEMA_KEYS}


def repair_brain_v4_schema(value: dict[str, Any]) -> dict[str, Any]:
    if has_exact_brain_v4_schema(value):
        return value
    error_type = value.get("error_type") or value.get("error_type_hint")
    root_cause = value.get("root_cause") or value.get("cause_label")
    likely_root_cause = value.get("likely_root_cause") or value.get("root_cause_summary") or value.get("cause")
    suggested_fix = value.get("suggested_fix") or value.get("fix")
    evidence_source = value.get("evidence") or value.get("terminal_error") or value.get("code_context")
    mapped = {
        "language": _string_value(value.get("language"), "unknown"),
        "framework": _string_value(value.get("framework"), "unknown"),
        "error_type": _string_value(error_type, "UnknownError"),
        "root_cause": _string_value(root_cause or likely_root_cause, "llm_diagnosis"),
        "likely_root_cause": _string_value(likely_root_cause or root_cause, ""),
        "evidence": _evidence_value(evidence_source, allow_empty=True),
        "suggested_fix": _string_value(suggested_fix, ""),
        "confidence": _confidence_value(value.get("confidence"), default=50),
        "safe_to_autofix": bool(value.get("safe_to_autofix")),
    }
    if not mapped["likely_root_cause"]:
        mapped["likely_root_cause"] = mapped["root_cause"]
    if not mapped["suggested_fix"]:
        mapped["suggested_fix"] = "Review the error and code context before changing code."
    return mapped


def _string_value(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def _evidence_value(value: Any, *, allow_empty: bool = False) -> list[str]:
    if isinstance(value, list):
        evidence = [str(item).strip() for item in value if str(item).strip()]
    else:
        evidence = [str(value or "").strip()] if str(value or "").strip() else []
    if allow_empty:
        return evidence
    return evidence or ["Model output did not include explicit evidence."]


def _collect_evidence_sources(value: dict[str, Any]) -> list[str]:
    evidence = []
    labels = [
        ("context", "Context"),
        ("code_context", "Context"),
        ("error_log", "Error log"),
        ("terminal_error", "Error log"),
        ("failing_line", "Failing line"),
    ]
    for key, label in labels:
        raw = value.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        text = " ".join(text.split())
        if len(text) > 240:
            text = text[:237].rstrip() + "..."
        evidence.append(f"{label}: {text}")
    return evidence


def _infer_error_type_from_text(text: str) -> str:
    patterns = (
        "ModuleNotFoundError",
        "NameError",
        "TypeError",
        "KeyError",
        "FileNotFoundError",
        "SyntaxError",
    )
    lowered = (text or "").lower()
    for pattern in patterns:
        if pattern.lower() in lowered:
            return pattern
    return ""


def _confidence_value(value: Any, *, default: int = 0) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    return max(0, min(100, int(round(numeric))))


def build_brain_v4_messages(user_content: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": TRAINING_SCHEMA_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def render_brain_v4_chat_prompt(tokenizer: Any, user_content: str) -> str:
    return (
        f"<|im_start|>system\n{TRAINING_SCHEMA_SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{user_content}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )


def build_brain_v4_user_content(
    *,
    language: str,
    framework: str,
    terminal_error: str,
    parsed_error: dict[str, Any] | None = None,
    code_context: str = "",
) -> str:
    terminal_error = terminal_error or ""
    code_context = code_context or ""
    if code_context.strip() and code_context.strip() != terminal_error.strip():
        return "\n".join(
            [
                f"language: {language or 'unknown'}",
                f"framework: {framework or 'unknown'}",
                f"error_type_hint: {(parsed_error or {}).get('type') or (parsed_error or {}).get('error_type') or ''}",
                "code_context:",
                code_context,
                "terminal_error:",
                terminal_error,
            ]
        ).strip()
    return terminal_error.strip()


def build_runtime_brain_v4_user_content(
    *,
    language: str,
    framework: str,
    terminal_error: str,
    parsed_error: dict[str, Any] | None = None,
    code_context: str = "",
) -> str:
    parsed_error = parsed_error or {}
    return "\n".join(
        [
            f"language: {language or 'unknown'}",
            f"framework: {framework or 'unknown'}",
            f"error_type: {parsed_error.get('type') or parsed_error.get('error_type') or ''}",
            f"failing_line: {_first_user_code_line(code_context)}",
            "code_context:",
            _trim_lines(code_context, max_lines=12, max_chars=1600),
            "error_log:",
            _trim_lines(terminal_error, max_lines=18, max_chars=2200),
        ]
    ).strip()


def _first_user_code_line(text: str) -> str:
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if ":" in stripped:
            return stripped.split(":", 1)[1].strip()
        return stripped
    return ""


def _trim_lines(text: str, *, max_lines: int, max_chars: int) -> str:
    lines = str(text or "").splitlines()
    trimmed = "\n".join(lines[-max_lines:])
    if len(trimmed) > max_chars:
        return trimmed[-max_chars:]
    return trimmed


def extract_json_candidate(text: str) -> str:
    text = _strip_markdown_fences(text or "")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return ""
    return text[start : end + 1].strip()


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def format_training_text(record: dict[str, Any], eos_token: str = "") -> str:
    output = record.get("output", {})
    if isinstance(output, str):
        output_text = json.dumps(json.loads(output), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        output_text = json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        f"<|im_start|>system\n{TRAINING_SCHEMA_SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{record.get('input', '')}<|im_end|>\n"
        f"<|im_start|>assistant\n{output_text}{eos_token}"
    )


def _parse_minimal_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]
        if line.startswith("- "):
            if isinstance(current, list):
                current.append(_coerce_scalar(line[2:].strip()))
            continue
        if ":" not in line or not isinstance(current, dict):
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            next_value: Any = [] if key == "target_modules" else {}
            current[key] = next_value
            stack.append((indent, next_value))
        else:
            current[key] = _coerce_scalar(value)
    return root


def _coerce_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return os.path.expandvars(value)
