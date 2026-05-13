# GhostFix Brain v4 LoRA Training

GhostFix Brain v4 is a specialized optional local debugging reasoner fine-tuned from a pretrained coder model. It is not a model trained from scratch.

## Why Pretrained + LoRA

GhostFix needs a model that already understands code, tracebacks, imports, frameworks, and terminal logs. A pretrained coder model provides that base knowledge. LoRA then teaches the model GhostFix-specific behavior:

- Return strict JSON.
- Explain root causes with evidence.
- Separate machine labels from human-readable diagnosis.
- Stay conservative about auto-fix.
- Respect local-first debugging workflows.

This is cheaper, faster, and safer than training a language model from scratch.

## Why Not Train From Scratch

Training from scratch would require a huge corpus, expensive GPU time, tokenizer work, evaluation infrastructure, and safety tuning. GhostFix already has a focused debugging dataset, so fine-tuning a local coder model is the right next step.

Recommended starter model for the first GPU test:

```text
Qwen2.5-Coder-0.5B-Instruct
```

Recommended model for better quality:

```text
Qwen2.5-Coder-1.5B-Instruct
```

Any compatible local causal/instruct coder model can be used later. Do not download models during GhostFix runtime.

## Prepare The Dataset

Run:

```powershell
python ml\prepare_brain_v4_lora_dataset.py
```

Outputs:

- `ml/processed/brain_v4_lora_train.jsonl`
- `ml/processed/brain_v4_lora_val.jsonl`
- `ml/reports/brain_v4_dataset_report.md`

Each JSONL row has:

```json
{
  "instruction": "Analyze the terminal error and return strict JSON.",
  "input": "terminal error, language, framework, code context, project hints",
  "output": {
    "language": "python",
    "framework": "python",
    "error_type": "TypeError",
    "root_cause": "typeerror_incompatible_type",
    "likely_root_cause": "An operation received a value with the wrong type.",
    "evidence": ["Traceback points to app.py line 8."],
    "suggested_fix": "Validate or convert the value before using it.",
    "confidence": 88,
    "safe_to_autofix": false
  }
}
```

The builder performs strict filtering:

- Rejects missing traceback or terminal error text.
- Rejects missing code context.
- Rejects missing error type, cause, or fix.
- Rejects vague fixes.
- Rejects corrupted/garbled fix text.
- Rejects unsafe auto-fix labels unless clearly deterministic and safe.
- Deduplicates near-identical records.
- Uses a hash split to reduce train/validation leakage.

## Training Config Template

Config template:

```text
ml/configs/brain_v4_lora_config.yaml
```

It includes:

- `base_model_path`
- `output_dir`
- `max_seq_length`
- LoRA rank/alpha/dropout
- learning rate
- epochs
- batch size
- gradient accumulation

Dataset preparation works locally and does not require a GPU. Actual LoRA training should run on a CUDA GPU.

See `docs/GPU_TRAINING_REQUIRED.md` before training.

## Hardware Requirements

Recommended:

- NVIDIA CUDA GPU for normal training.
- Enough VRAM for the selected coder model and sequence length.
- Start with `max_seq_length: 4096`, then reduce it if memory is tight.
- Local CPU training is unsupported for real use.
- `--allow-cpu` is only for tiny developer smoke tests and may still fail on low-memory machines.

The scripts fail gracefully if dependencies, model files, adapter files, or GPU are missing.

## Train

Training script for a GPU environment:

```powershell
python ml\train_brain_v4_lora.py --dry-run
python ml\train_brain_v4_lora.py
```

For a tiny CPU smoke test only:

```powershell
python ml\train_brain_v4_lora.py --allow-cpu --dry-run
python ml\train_brain_v4_lora.py --allow-cpu --max-train-records 8 --max-val-records 2
```

Do not use `--allow-cpu` for real training.

The training script:

1. Loads `ml/configs/brain_v4_lora_config.yaml`.
2. Loads the local base coder model from `base_model_path`.
3. Uses `transformers`, `datasets`, `peft`, and `torch` if installed.
4. Trains LoRA adapters on `brain_v4_lora_train.jsonl`.
5. Validates on `brain_v4_lora_val.jsonl`.
6. Saves adapters to `ml/models/ghostfix_brain_v4_lora/`.

It uses `local_files_only=True` and does not download a model.

Useful dependencies for the training environment:

```powershell
pip install transformers datasets peft accelerate torch pyyaml
```

Install the PyTorch build that matches your GPU/CUDA setup. Do not commit the downloaded base model to this repo.

## Evaluate

Evaluation should check:

- Strict JSON validity.
- Correct language/framework/error type.
- Root cause quality.
- Evidence grounding.
- Suggested fix usefulness.
- Confidence calibration.
- Safety behavior: model output must not enable auto-fix by itself.

Use existing GhostFix demo fixtures and real-world validation records as a starting point.

Evaluation script:

```powershell
python ml\evaluate_brain_v4.py
```

Outputs:

- `ml/reports/brain_v4_eval_report.json`
- `ml/reports/brain_v4_eval_report.md`

Metrics:

- `valid_json_rate`
- `error_type_accuracy`
- `root_cause_accuracy`
- `safe_to_autofix_accuracy`
- `average_confidence`
- `malformed_output_count`

If the model or adapter is unavailable, evaluation writes an unavailable report instead of crashing.

## Inference Wrapper

Brain v4 inference helper:

```text
ml/brain_v4_inference.py
```

It loads the local base model plus the LoRA adapter when available and returns either:

- `{"available": true, "diagnosis": {...}}`
- `{"available": false, "reason": "..."}`
- `{"available": true, "malformed": true, "raw_output": "..."}`

Malformed model output is rejected unless it parses as the strict GhostFix JSON schema.

## Plug Into GhostFix

Brain v4 is integrated as an optional guarded runtime reasoning path. Enable it only when compatible local model and adapter files are available:

```powershell
$env:GHOSTFIX_BRAIN_V4="1"
$env:GHOSTFIX_BASE_MODEL_PATH="ml/models/base_model"
```

At runtime, GhostFix keeps this priority:

1. Deterministic rules and framework rules.
2. Memory and retriever.
3. Brain v4 reasoning when enabled and fast paths are insufficient.
4. Fallback diagnosis.
5. Safety policy as the final auto-fix gate.

Brain v4 must not bypass `core/safety_policy.py`. Non-Python auto-fix remains disabled until separate language-specific patch validation exists. Brain v4 output remains advisory and cannot make a patch safe by itself.

## Privacy

All dataset preparation, training, evaluation, and inference scripts are local-only. They do not upload datasets, logs, code, prompts, metrics, or model outputs anywhere.

Data leaves your machine only if you manually upload it elsewhere.
