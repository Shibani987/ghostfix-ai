import json
import pickle
import re
from pathlib import Path


MODEL_DIR = Path("ml/models")

VECTORIZER_PATH = MODEL_DIR / "vectorizer_v2.pkl"
RETRIEVER_PATH = MODEL_DIR / "retriever_v2.pkl"
RECORDS_PATH = MODEL_DIR / "retriever_records_v2.json"

# Backward-compatible fallback for older local installs.
V1_VECTORIZER_PATH = MODEL_DIR / "tfidf_vectorizer_v1.pkl"
V1_RETRIEVER_PATH = MODEL_DIR / "retriever_v1.pkl"
V1_RECORDS_PATH = MODEL_DIR / "train_records.json"


def _existing_or_fallback(primary: Path, fallback: Path) -> Path:
    return primary if primary.exists() else fallback


def load_model():
    vectorizer_path = _existing_or_fallback(VECTORIZER_PATH, V1_VECTORIZER_PATH)
    retriever_path = _existing_or_fallback(RETRIEVER_PATH, V1_RETRIEVER_PATH)
    records_path = _existing_or_fallback(RECORDS_PATH, V1_RECORDS_PATH)

    with open(vectorizer_path, "rb") as f:
        vectorizer = pickle.load(f)

    with open(retriever_path, "rb") as f:
        retriever = pickle.load(f)

    with open(records_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    return vectorizer, retriever, records


def extract_missing_package(text: str):
    match = re.search(r"No module named ['\"]([^'\"]+)['\"]", text)
    return match.group(1).lower() if match else None


def extract_error_type(text: str) -> str:
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b", text or "")
    return match.group(1) if match else ""


def extract_error_message(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    for line in reversed(lines):
        if re.search(r"\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception):", line):
            return line
    return lines[-1] if lines else ""


def extract_failing_line(text: str) -> str:
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        if re.search(r'File ".*?", line \d+', line):
            for candidate in lines[i + 1:i + 4]:
                stripped = candidate.strip()
                if not stripped or stripped.startswith(("^", "~")):
                    continue
                if re.search(r"\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception):", stripped):
                    break
                return stripped
    return ""


def tokens(text: str) -> set[str]:
    ignored = {
        "traceback", "most", "recent", "call", "last", "file", "line",
        "error", "exception", "return", "print", "self", "none", "true",
        "false", "with", "open", "from", "import", "python", "site",
        "packages", "usr", "local", "lib",
    }
    found = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text or "")
    return {token.lower() for token in found if token.lower() not in ignored}


def overlap_score(left: str, right: str) -> float:
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def rerank_score(
    *,
    query_error_text: str,
    query_context: str,
    record: dict,
    distance: float,
) -> dict:
    cosine_similarity = max(0.0, min(1.0, 1 - float(distance)))

    query_error_type = extract_error_type(query_error_text)
    record_error_type = record.get("error_type") or extract_error_type(record.get("error", ""))
    error_type_match = bool(query_error_type and record_error_type and query_error_type == record_error_type)

    query_message = extract_error_message(query_error_text)
    record_message = extract_error_message(record.get("error", ""))
    message_overlap = overlap_score(query_message or query_error_text, record_message or record.get("error", ""))

    query_failing_line = extract_failing_line(query_error_text)
    query_code = "\n".join(part for part in [query_context, query_failing_line] if part)
    record_code = "\n".join(part for part in [record.get("context", ""), record.get("failing_line", "")] if part)
    context_overlap = overlap_score(query_code, record_code)

    quality_score = float(record.get("quality_score") or 0)
    quality_bonus = min(quality_score, 10.0) / 10.0

    combined = (
        0.50 * cosine_similarity
        + 0.22 * (1.0 if error_type_match else 0.0)
        + 0.16 * message_overlap
        + 0.09 * context_overlap
        + 0.03 * quality_bonus
    )

    return {
        "score": round(combined * 100, 2),
        "cosine_similarity": round(cosine_similarity, 4),
        "error_type_match": error_type_match,
        "message_overlap": round(message_overlap, 4),
        "context_overlap": round(context_overlap, 4),
        "query_error_type": query_error_type,
        "record_error_type": record_error_type,
    }


def build_query(error_text: str, context: str = "", language: str = "python") -> str:
    return "\n".join([
        f"LANGUAGE: {language}",
        f"ERROR: {error_text}",
        f"CONTEXT: {context}",
    ]).strip()


def predict_fix(
    error_text: str,
    context: str = "",
    language: str = "python",
    top_k: int = 3,
    min_confidence: float = 0.0,
):
    vectorizer, retriever, records = load_model()

    missing_package = extract_missing_package(error_text)
    X = vectorizer.transform([build_query(error_text, context, language)])

    search_k = min(max(top_k * 4, top_k), len(records))
    distances, indices = retriever.kneighbors(X, n_neighbors=search_k)

    candidates = []
    seen = set()

    for distance, idx in zip(distances[0], indices[0]):
        record = records[int(idx)]
        score_parts = rerank_score(
            query_error_text=error_text,
            query_context=context,
            record=record,
            distance=float(distance),
        )

        matched_error = record.get("error", "").strip()
        cause = record.get("cause", "").strip()
        fix = record.get("fix", "").strip()

        if missing_package:
            combined = f"{matched_error} {record.get('context', '')} {fix}".lower()
            if missing_package not in combined:
                continue

        unique_key = (matched_error.lower(), cause.lower(), fix.lower())
        if unique_key in seen:
            continue
        seen.add(unique_key)

        if score_parts["score"] < min_confidence:
            continue

        candidates.append({
            "score": score_parts["score"],
            "confidence": score_parts["score"],
            "distance": round(float(distance), 4),
            "cosine_similarity": score_parts["cosine_similarity"],
            "error_type_match": score_parts["error_type_match"],
            "message_overlap": score_parts["message_overlap"],
            "context_overlap": score_parts["context_overlap"],
            "error_type": record.get("error_type"),
            "matched_error": matched_error,
            "cause": cause,
            "fix": fix,
            "context": record.get("context"),
            "source": record.get("source", ""),
            "source_url": record.get("source_url", ""),
            "quality_score": record.get("quality_score", 0),
        })

    candidates.sort(key=lambda item: item["score"], reverse=True)
    results = candidates[:top_k]

    return results


if __name__ == "__main__":
    error = input("Paste error: ").strip()
    context = input("Paste context (optional): ").strip()

    results = predict_fix(error, context=context)

    print("\n===== GHOSTFIX RETRIEVER V2 SUGGESTIONS =====")

    if not results:
        print("No similar real-debug fix found.")
    else:
        for i, r in enumerate(results, start=1):
            print(f"\n#{i} Score: {r['score']}%")
            print("Type:", r["error_type"])
            print("Source:", r["source"])
            print(
                "Signals:",
                f"cosine={r['cosine_similarity']}",
                f"type_match={r['error_type_match']}",
                f"message_overlap={r['message_overlap']}",
                f"context_overlap={r['context_overlap']}",
            )
            print("Matched:", r["matched_error"][:300])
            print("Cause:", r["cause"])
            print("Fix:", r["fix"])
