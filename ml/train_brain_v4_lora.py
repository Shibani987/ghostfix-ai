from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.brain_v4_inference import DEFAULT_CONFIG, TRAINING_SCHEMA_SYSTEM_PROMPT, load_config

CPU_TRAINING_REFUSAL = (
    "CUDA GPU is not available. Real Brain v4 LoRA training is not supported on CPU. "
    "Use Kaggle, Colab, RunPod, or another CUDA GPU environment. "
    "Use --allow-cpu only for tiny developer smoke tests."
)
CPU_SMOKE_TEST_WARNING = (
    "WARNING: --allow-cpu is only for tiny developer smoke tests. "
    "It is not supported for real Brain v4 training and may still fail on low-memory machines."
)
COMMON_ERROR_TYPES = (
    "ModuleNotFoundError",
    "NameError",
    "TypeError",
    "FileNotFoundError",
    "KeyError",
    "SyntaxError",
    "JSONDecodeError",
)
SCHEMA_ONLY_INSTRUCTION = "Return ONLY valid JSON with exact schema"
BALANCED_SAMPLE_SEED = 404


@dataclass
class TrainingReadiness:
    ready: bool
    reason: str
    config: dict[str, Any]


def main() -> int:
    parser = argparse.ArgumentParser(description="Train GhostFix Brain v4 LoRA adapter in a GPU environment.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to Brain v4 LoRA YAML config.")
    parser.add_argument(
        "--allow-cpu",
        action="store_true",
        help="Allow CPU execution only for tiny developer smoke tests. May fail on low-memory machines.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only validate config, dependencies, data, model, and device.")
    parser.add_argument("--max-train-records", type=int, default=0, help="Optional cap for tiny training smoke tests.")
    parser.add_argument("--max-val-records", type=int, default=0, help="Optional cap for tiny validation smoke tests.")
    parser.add_argument("--balanced-sample", action="store_true", help="Use deterministic balanced sampling for capped train records.")
    parser.add_argument("--overfit-smoke", action="store_true", help="Train 20 high-quality balanced records for extra epochs.")
    args = parser.parse_args()

    if args.allow_cpu:
        print(CPU_SMOKE_TEST_WARNING, file=sys.stderr)

    readiness = check_training_ready(args.config, require_gpu=not args.allow_cpu)
    if not readiness.ready:
        print(f"Brain v4 training unavailable: {readiness.reason}")
        return 1
    if args.dry_run:
        print("Brain v4 training dry run passed.")
        return 0
    try:
        train(
            readiness.config,
            max_train_records=args.max_train_records or None,
            max_val_records=args.max_val_records or None,
            balanced_sample=args.balanced_sample,
            overfit_smoke=args.overfit_smoke,
        )
    except Exception as exc:
        print(f"Brain v4 training failed: {exc}")
        return 1
    print(f"Brain v4 LoRA adapter saved to {readiness.config.get('output_dir')}")
    return 0


def check_training_ready(config_path: str | Path = DEFAULT_CONFIG, require_gpu: bool = True) -> TrainingReadiness:
    config = load_config(config_path)
    if not config:
        return TrainingReadiness(False, f"Config not found or invalid: {config_path}", config)
    base_model_path = Path(str(config.get("base_model_path") or "")).expanduser()
    if not base_model_path.exists():
        return TrainingReadiness(False, f"Base model path does not exist: {base_model_path}", config)
    data = config.get("data") or {}
    train_file = Path(str(data.get("train_file") or "")).expanduser()
    val_file = Path(str(data.get("val_file") or "")).expanduser()
    if not train_file.exists():
        return TrainingReadiness(False, f"Training file missing: {train_file}", config)
    if not val_file.exists():
        return TrainingReadiness(False, f"Validation file missing: {val_file}", config)
    try:
        import datasets  # noqa: F401
        import peft  # noqa: F401
        import torch
        import transformers  # noqa: F401
    except Exception as exc:
        return TrainingReadiness(False, f"Missing training dependency: {exc}", config)
    if require_gpu and not torch.cuda.is_available():
        return TrainingReadiness(False, CPU_TRAINING_REFUSAL, config)
    return TrainingReadiness(True, "Training environment is ready.", config)


def train(
    config: dict[str, Any],
    *,
    max_train_records: int | None = None,
    max_val_records: int | None = None,
    balanced_sample: bool = False,
    overfit_smoke: bool = False,
) -> None:
    import torch
    from datasets import Dataset, DatasetDict, load_dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments

    base_model_path = Path(str(config["base_model_path"])).expanduser()
    output_dir = Path(str(config.get("output_dir") or "ml/models/ghostfix_brain_v4_lora"))
    data = config.get("data") or {}
    training = config.get("training") or {}
    lora = config.get("lora") or {}

    tokenizer = AutoTokenizer.from_pretrained(
        str(base_model_path),
        local_files_only=True,
        trust_remote_code=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    dataset = load_dataset(
        "json",
        data_files={
            "train": str(data.get("train_file")),
            "validation": str(data.get("val_file")),
        },
    )
    if overfit_smoke:
        max_train_records = 20
        balanced_sample = True
        training["epochs"] = max(float(training.get("epochs", 3)), 8)
    if max_train_records:
        train_records = [dict(row) for row in dataset["train"]]
        if overfit_smoke:
            selected_train = select_overfit_smoke_records(train_records, max_train_records)
        elif balanced_sample:
            selected_train = select_balanced_training_records(train_records, max_train_records)
        else:
            selected_train = select_shuffled_training_records(train_records, max_train_records)
        dataset = DatasetDict({"train": Dataset.from_list(selected_train), "validation": dataset["validation"]})
    if max_val_records:
        dataset["validation"] = dataset["validation"].select(range(min(max_val_records, len(dataset["validation"]))))
    print_dataset_selection_debug([dict(row) for row in dataset["train"]], split_name="train")
    max_seq_length = int(training.get("max_seq_length", 4096))

    def tokenize(batch: dict[str, list[Any]]) -> dict[str, Any]:
        records = [
            {"instruction": instruction, "input": input_text, "output": output}
            for instruction, input_text, output in zip(batch["instruction"], batch["input"], batch["output"])
        ]
        return tokenize_records(tokenizer, records, max_seq_length=max_seq_length)

    tokenized = dataset.map(tokenize, batched=True, remove_columns=dataset["train"].column_names)
    tokenized.set_format(type="python")
    validate_flat_tokenized_rows(tokenized["train"])
    validate_flat_tokenized_rows(tokenized["validation"])
    print(
        f"Tokenized Brain v4 data: train={len(tokenized['train'])}, validation={len(tokenized['validation'])}, "
        "labels are flat list[int].",
        flush=True,
    )

    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        str(base_model_path),
        local_files_only=True,
        trust_remote_code=True,
        torch_dtype=dtype,
        device_map="auto" if torch.cuda.is_available() else None,
    )
    try:
        model = prepare_model_for_kbit_training(model)
    except Exception:
        pass

    peft_config = LoraConfig(
        r=int(lora.get("lora_r", 16)),
        lora_alpha=int(lora.get("lora_alpha", 32)),
        lora_dropout=float(lora.get("lora_dropout", 0.05)),
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=list(lora.get("target_modules") or []),
    )
    model = get_peft_model(model, peft_config)
    args = TrainingArguments(
        output_dir=str(output_dir),
        per_device_train_batch_size=int(training.get("batch_size", 2)),
        per_device_eval_batch_size=int(training.get("batch_size", 2)),
        gradient_accumulation_steps=int(training.get("gradient_accumulation", 8)),
        learning_rate=float(training.get("learning_rate", 2e-4)),
        num_train_epochs=float(training.get("epochs", 3)),
        evaluation_strategy="epoch",
        save_strategy="epoch",
        logging_steps=10,
        report_to=[],
        fp16=torch.cuda.is_available(),
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["validation"],
        tokenizer=tokenizer,
        data_collator=CausalLMPaddingCollator(tokenizer),
    )
    trainer.train()
    output_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))


def tokenize_records(tokenizer: Any, records: list[dict[str, Any]], *, max_seq_length: int) -> dict[str, list[list[int]]]:
    rows = [
        tokenize_sft_record(tokenizer, record, max_seq_length=max_seq_length)
        for record in records
    ]
    result = {
        "input_ids": [row["input_ids"] for row in rows],
        "attention_mask": [row["attention_mask"] for row in rows],
        "labels": [row["labels"] for row in rows],
    }
    print_label_debug(tokenizer, result)
    return result


def tokenize_sft_record(tokenizer: Any, record: dict[str, Any], *, max_seq_length: int) -> dict[str, list[int]]:
    prompt_text = format_training_prompt(record)
    target_text = compact_output_text(record.get("output", {}))
    prompt_ids = _encode_text(tokenizer, prompt_text, add_special_tokens=True)
    target_ids = _encode_text(tokenizer, target_text, add_special_tokens=False)
    eos_id = _eos_token_id(tokenizer)
    if eos_id is None:
        eos_ids: list[int] = []
    else:
        eos_ids = [int(eos_id)]
    target_with_eos = target_ids + eos_ids
    if len(target_with_eos) >= max_seq_length:
        raise ValueError(
            f"Target JSON is too long for max_seq_length={max_seq_length}; "
            "increase max_seq_length so the assistant target is not truncated."
        )
    prompt_budget = max_seq_length - len(target_with_eos)
    prompt_ids = prompt_ids[-prompt_budget:] if len(prompt_ids) > prompt_budget else prompt_ids
    input_ids = prompt_ids + target_with_eos
    labels = [-100] * len(prompt_ids) + target_with_eos.copy()
    attention_mask = [1] * len(input_ids)
    return {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "labels": labels,
    }


def format_training_prompt(record: dict[str, Any]) -> str:
    return (
        f"<|im_start|>system\n{TRAINING_SCHEMA_SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{record.get('input', '')}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )


def compact_output_text(output: Any) -> str:
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return output.strip()
        return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _encode_text(tokenizer: Any, text: str, *, add_special_tokens: bool) -> list[int]:
    encoded = tokenizer(
        [text],
        truncation=False,
        padding=False,
        add_special_tokens=add_special_tokens,
    )
    input_ids = encoded.get("input_ids", encoded)
    if input_ids and isinstance(input_ids[0], list):
        input_ids = input_ids[0]
    return _flat_int_list(input_ids)


def _eos_token_id(tokenizer: Any) -> int | None:
    value = getattr(tokenizer, "eos_token_id", None)
    if value is not None:
        return int(value)
    eos_token = getattr(tokenizer, "eos_token", None)
    if not eos_token:
        return None
    encoded = _encode_text(tokenizer, str(eos_token), add_special_tokens=False)
    return encoded[0] if encoded else None


def print_label_debug(tokenizer: Any, tokenized: dict[str, list[list[int]]]) -> None:
    labels = tokenized.get("labels") or []
    total = sum(len(row) for row in labels)
    supervised = sum(1 for row in labels for value in row if value != -100)
    percent = (supervised / total * 100.0) if total else 0.0
    print(f"Brain v4 SFT supervised label tokens: {supervised}/{total} ({percent:.2f}%)", flush=True)
    if not labels:
        return
    target_ids = [value for value in labels[0] if value != -100]
    preview = decode_token_ids(tokenizer, target_ids[:160])
    print(f"Brain v4 SFT sample target labels: {preview}", flush=True)


def decode_token_ids(tokenizer: Any, token_ids: list[int]) -> str:
    decode = getattr(tokenizer, "decode", None)
    if callable(decode):
        try:
            return str(decode(token_ids, skip_special_tokens=False))
        except TypeError:
            return str(decode(token_ids))
    return " ".join(str(item) for item in token_ids)


def select_shuffled_training_records(
    records: list[dict[str, Any]],
    limit: int,
    *,
    seed: int = BALANCED_SAMPLE_SEED,
) -> list[dict[str, Any]]:
    if limit >= len(records):
        return list(records)
    shuffled = list(records)
    random.Random(seed).shuffle(shuffled)
    return shuffled[:limit]


def select_balanced_training_records(
    records: list[dict[str, Any]],
    limit: int,
    *,
    seed: int = BALANCED_SAMPLE_SEED,
) -> list[dict[str, Any]]:
    if limit >= len(records):
        return list(records)
    rng = random.Random(seed)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    schema_records = []
    real_records = []
    for record in records:
        output = _record_output(record)
        error_type = str(output.get("error_type") or "UnknownError")
        buckets[error_type].append(record)
        if record.get("instruction") == SCHEMA_ONLY_INSTRUCTION:
            schema_records.append(record)
        else:
            real_records.append(record)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    rng.shuffle(schema_records)
    rng.shuffle(real_records)

    selected: list[dict[str, Any]] = []
    seen: set[int] = set()

    def add(record: dict[str, Any]) -> bool:
        if len(selected) >= limit:
            return False
        marker = id(record)
        if marker in seen:
            return False
        seen.add(marker)
        selected.append(record)
        return True

    for error_type in COMMON_ERROR_TYPES:
        for record in buckets.get(error_type, []):
            if add(record):
                break
    if limit >= 2:
        add_ratio_records(schema_records, selected, seen, max(1, limit // 3), limit)
        add_ratio_records(real_records, selected, seen, max(1, limit // 3), limit)
    error_cycle = list(COMMON_ERROR_TYPES)
    while len(selected) < limit and any(buckets.get(error_type) for error_type in error_cycle):
        progressed = False
        for error_type in error_cycle:
            while buckets.get(error_type):
                record = buckets[error_type].pop()
                if add(record):
                    progressed = True
                    break
            if len(selected) >= limit:
                break
        if not progressed:
            break
    remaining = [record for record in records if id(record) not in seen]
    rng.shuffle(remaining)
    for record in remaining:
        if not add(record):
            break
    return selected


def select_overfit_smoke_records(
    records: list[dict[str, Any]],
    limit: int = 20,
    *,
    seed: int = BALANCED_SAMPLE_SEED,
) -> list[dict[str, Any]]:
    high_quality = [
        record
        for record in records
        if _record_output(record).get("error_type") in COMMON_ERROR_TYPES
        and int(_record_output(record).get("confidence") or 0) >= 80
        and str(_record_output(record).get("root_cause") or "").lower() not in {"", "unknown", "llm_diagnosis"}
        and str(_record_output(record).get("suggested_fix") or "").strip()
    ]
    pool = high_quality or records
    return select_balanced_training_records(pool, limit, seed=seed)


def add_ratio_records(
    candidates: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    seen: set[int],
    target_count: int,
    limit: int,
) -> None:
    for record in candidates:
        if len(selected) >= limit or sum(1 for item in selected if item.get("instruction") == record.get("instruction")) >= target_count:
            break
        marker = id(record)
        if marker in seen:
            continue
        seen.add(marker)
        selected.append(record)


def print_dataset_selection_debug(records: list[dict[str, Any]], *, split_name: str) -> None:
    error_counts = Counter(str(_record_output(record).get("error_type") or "UnknownError") for record in records)
    root_counts = Counter(str(_record_output(record).get("root_cause") or "unknown") for record in records)
    print(f"Selected {split_name} count: {len(records)}", flush=True)
    print(f"Selected {split_name} error_type distribution: {dict(error_counts.most_common())}", flush=True)
    print(f"Selected {split_name} root_cause distribution: {dict(root_counts.most_common(25))}", flush=True)


def _record_output(record: dict[str, Any]) -> dict[str, Any]:
    output = record.get("output") or {}
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return output if isinstance(output, dict) else {}


def validate_flat_tokenized_rows(rows: Any, limit: int = 8) -> None:
    for index, row in enumerate(rows):
        if index >= limit:
            break
        for key in ("input_ids", "attention_mask", "labels"):
            values = row[key]
            if not isinstance(values, list):
                raise TypeError(f"{key} must be list[int], got {type(values).__name__}")
            if values and isinstance(values[0], list):
                raise ValueError(f"{key} must be flat list[int], got nested list at row {index}")
            if not all(isinstance(item, int) for item in values):
                raise TypeError(f"{key} must contain only int values at row {index}")


class CausalLMPaddingCollator:
    def __init__(self, tokenizer: Any):
        self.tokenizer = tokenizer

    def __call__(self, features: list[dict[str, Any]]) -> dict[str, Any]:
        import torch

        pad_token_id = self.tokenizer.pad_token_id
        if pad_token_id is None:
            pad_token_id = self.tokenizer.eos_token_id if self.tokenizer.eos_token_id is not None else 0
        max_length = max(len(feature["input_ids"]) for feature in features)
        batch = {"input_ids": [], "attention_mask": [], "labels": []}
        for feature in features:
            input_ids = _flat_int_list(feature["input_ids"])
            attention_mask = _flat_int_list(feature.get("attention_mask") or [1] * len(input_ids))
            labels = _flat_int_list(feature.get("labels") or input_ids)
            pad_length = max_length - len(input_ids)
            batch["input_ids"].append(input_ids + [int(pad_token_id)] * pad_length)
            batch["attention_mask"].append(attention_mask + [0] * pad_length)
            batch["labels"].append(labels + [-100] * pad_length)
        return {key: torch.tensor(value, dtype=torch.long) for key, value in batch.items()}


def _flat_int_list(value: Any) -> list[int]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, list):
        raise TypeError(f"Expected a list of token ids, got {type(value).__name__}")
    if value and isinstance(value[0], list):
        raise ValueError("Tokenized field must be a flat list[int], not list[list[int]].")
    return [int(item) for item in value]


def readiness_dict(readiness: TrainingReadiness) -> dict[str, Any]:
    data = asdict(readiness)
    data.pop("config", None)
    return data


if __name__ == "__main__":
    sys.exit(main())
