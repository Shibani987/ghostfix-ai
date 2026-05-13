from __future__ import annotations

from typing import Any


def predict_fix(
    error_text: str,
    context: str = "",
    language: str = "python",
    top_k: int = 3,
    min_confidence: float = 0.0,
) -> list[dict[str, Any]]:
    try:
        from ml.embedding_retriever import predict_fix as embedding_predict

        results = embedding_predict(
            error_text=error_text,
            context=context,
            language=language,
            top_k=top_k,
            min_confidence=min_confidence,
        )
        if results:
            return _normalize_results(results, "embedding_retriever")
    except Exception:
        pass

    from ml.predict_fix import predict_fix as tfidf_predict

    return _normalize_results(
        tfidf_predict(
            error_text=error_text,
            context=context,
            language=language,
            top_k=top_k,
            min_confidence=min_confidence,
        ),
        "tfidf_retriever",
    )


def _normalize_results(results: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    normalized = []
    for result in results:
        item = dict(result)
        item.setdefault("language", "python")
        item.setdefault("root_cause", item.get("cause", ""))
        item.setdefault("safe_to_autofix", False)
        item["source"] = item.get("source") or source
        item["retriever_backend"] = source
        normalized.append(item)
    return normalized
