from __future__ import annotations

from pathlib import Path

MODEL_ID = "Qwen/Qwen2.5-Coder-0.5B-Instruct"
TARGET_DIR = Path("ml/models/base_model")


def model_exists(path: Path) -> bool:
    return path.exists() and any(path.iterdir())


def main() -> None:
    if model_exists(TARGET_DIR):
        print(f"Base model already exists at {TARGET_DIR}. Skipping download.")
        return

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: huggingface_hub. Install with:\n"
            "pip install huggingface_hub transformers peft accelerate torch"
        ) from exc

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {MODEL_ID} to {TARGET_DIR}...")
    snapshot_download(
        repo_id=MODEL_ID,
        local_dir=str(TARGET_DIR),
        local_dir_use_symlinks=False,
    )
    print(f"Base model ready at {TARGET_DIR}.")


if __name__ == "__main__":
    main()
