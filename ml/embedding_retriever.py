from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


MODEL_DIR = Path("ml/models")
DEFAULT_EMBEDDING_MODEL = MODEL_DIR / "all-MiniLM-L6-v2"
DEFAULT_RECORDS = MODEL_DIR / "retriever_records_v2.json"


class EmbeddingRetrieverUnavailable(RuntimeError):
    pass


def predict_fix(
    error_text: str,
    context: str = "",
    language: str = "python",
    top_k: int = 3,
    min_confidence: float = 0.0,
    model_path: str | Path = DEFAULT_EMBEDDING_MODEL,
    records_path: str | Path = DEFAULT_RECORDS,
) -> list[dict[str, Any]]:
    """Local optional embedding retrieval.

    This never downloads a model implicitly. The sentence-transformers package
    and the model directory must already exist locally.
    """
    model_path = Path(model_path)
    records_path = Path(records_path)
    if not model_path.exists():
        raise EmbeddingRetrieverUnavailable(f"embedding model not found: {model_path}")
    if not records_path.exists():
        raise EmbeddingRetrieverUnavailable(f"retriever records not found: {records_path}")

    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:
        raise EmbeddingRetrieverUnavailable(f"sentence-transformers unavailable: {exc}") from exc

    records = _load_records(records_path)
    if not records:
        return []

    model = SentenceTransformer(str(model_path), local_files_only=True)
    query = _build_text({
        "language": language,
        "error": error_text,
        "context": context,
    })
    texts = [_build_text(record) for record in records]
    embeddings = model.encode([query, *texts], normalize_embeddings=True)
    query_embedding = embeddings[0]
    record_embeddings = embeddings[1:]

    results = []
    for record, embedding in zip(records, record_embeddings):
        confidence = max(0.0, min(100.0, _cosine(query_embedding, embedding) * 100.0))
        if confidence < min_confidence:
            continue
        results.append(_to_result(record, confidence))

    results.sort(key=lambda item: item["confidence"], reverse=True)
    return results[:top_k]


def _load_records(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _build_text(record: dict[str, Any]) -> str:
    return "\n".join([
        f"LANGUAGE: {record.get('language', 'python')}",
        f"ERROR_TYPE: {record.get('error_type', '')}",
        f"ROOT_CAUSE: {record.get('root_cause') or record.get('cause', '')}",
        f"CONTEXT: {record.get('context', '')}",
        f"FIX: {record.get('fix', '')}",
        f"ERROR: {record.get('error', '')}",
    ])


def _to_result(record: dict[str, Any], confidence: float) -> dict[str, Any]:
    return {
        "score": round(confidence, 2),
        "confidence": round(confidence, 2),
        "error_type": record.get("error_type"),
        "matched_error": record.get("error", ""),
        "cause": record.get("root_cause") or record.get("cause", ""),
        "fix": record.get("fix", ""),
        "context": record.get("context", ""),
        "source": "embedding_retriever",
        "language": record.get("language", "python"),
        "root_cause": record.get("root_cause") or record.get("cause", ""),
        "safe_to_autofix": bool(record.get("safe_to_autofix", False)),
    }


def _cosine(left, right) -> float:
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
    right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)
