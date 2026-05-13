# GPU Training Required For Brain v4

GhostFix Brain v4 dataset preparation works locally. Actual LoRA training should run on a CUDA GPU.

Local CPU training is unsupported for real use. Loading and fine-tuning coder language models requires far more memory bandwidth and RAM than a normal laptop CPU workflow can provide. Even a small 0.5B model can be slow, unstable, or fail with out-of-memory errors on CPU. A 1.5B model is especially impractical for local CPU training.

The local project status should be read as:

```text
Brain v4 dataset + training pipeline ready.
Actual LoRA training requires GPU.
Local CPU training is not supported except tiny developer smoke tests.
```

## Recommended GPU Options

- Kaggle GPU notebook: best free first option when GPU quota is available.
- Google Colab GPU: good for quick experiments and notebook-driven training.
- RunPod or Lambda Labs: good paid options when you need predictable GPU time.

Use an NVIDIA CUDA GPU runtime. CPU runtimes are not supported for real training.

## Recommended Models

Start with:

```text
Qwen2.5-Coder-0.5B-Instruct
```

This is the recommended first GPU test because it is smaller and easier to fit.

For better quality, use:

```text
Qwen2.5-Coder-1.5B-Instruct
```

The 1.5B model should still be trained on GPU, not local CPU.

## Files To Upload

Upload the GhostFix project files needed by the training pipeline:

- `ml/train_brain_v4_lora.py`
- `ml/brain_v4_inference.py`
- `ml/configs/brain_v4_lora_config.yaml`
- `ml/processed/brain_v4_lora_train.jsonl`
- `ml/processed/brain_v4_lora_val.jsonl`

You also need the selected base model available in the GPU environment. Either download it inside the notebook from the model host, or attach it as notebook input/storage. Do not commit downloaded base model weights to this repo.

In the GPU environment, update `base_model_path` in `ml/configs/brain_v4_lora_config.yaml` so it points to the model location there. Keep:

```text
output_dir: ml/models/ghostfix_brain_v4_lora
```

## Train On GPU

Install training dependencies in the GPU notebook:

```bash
pip install transformers datasets peft accelerate torch pyyaml
```

Then run:

```bash
python ml/train_brain_v4_lora.py --dry-run
python ml/train_brain_v4_lora.py
```

Do not pass `--allow-cpu` for real training. That flag exists only for tiny developer smoke tests and may still fail on low-memory machines.

## Download The LoRA Adapter

After training, download the adapter output directory from the GPU environment:

```text
ml/models/ghostfix_brain_v4_lora/
```

Copy that directory back into this local project at the same path:

```text
ml/models/ghostfix_brain_v4_lora/
```

The adapter directory should contain the trained LoRA adapter files and tokenizer files saved by `train_brain_v4_lora.py`. Keep the base model separate from the repo and point local inference config/env vars to its local path when you are ready to test inference.
