from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_SOURCES = [
    Path("ml/processed/ghostfix_dataset_v3_strict.jsonl"),
    Path("ml/processed/ghostfix_dataset_v3_hardneg.jsonl"),
    Path("ml/processed/ghostfix_dataset_v3_unsafe_recall_boost_v1.jsonl"),
    Path("ml/processed/ghostfix_real_world_eval_clean.jsonl"),
]
TRAIN_OUT = Path("ml/processed/brain_v4_lora_train.jsonl")
VAL_OUT = Path("ml/processed/brain_v4_lora_val.jsonl")
REPORT_OUT = Path("ml/reports/brain_v4_dataset_report.md")
INSTRUCTION = "Analyze the terminal error and return strict JSON."
SCHEMA_ONLY_INSTRUCTION = "Return ONLY valid JSON with exact schema"
JSON_ONLY_SYSTEM = "You are GhostFix Brain v4. Return ONLY valid JSON. No explanation."
SCHEMA_ONLY_DUPLICATES = 4
FORBIDDEN_TRAINING_PATTERNS = ("error_type_hint", "code_context", "project_hints", "terminal_error")
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
BRAIN_V4_JSON_SCHEMA = {
    "type": "object",
    "required": list(BRAIN_V4_SCHEMA_KEYS),
    "additionalProperties": False,
    "properties": {
        "language": {"type": "string", "minLength": 1},
        "framework": {"type": "string", "minLength": 1},
        "error_type": {"type": "string", "minLength": 1},
        "root_cause": {"type": "string", "minLength": 1},
        "likely_root_cause": {"type": "string", "minLength": 1},
        "evidence": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "suggested_fix": {"type": "string", "minLength": 1},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "safe_to_autofix": {"type": "boolean"},
    },
}
VAGUE_FIX_PATTERNS = [
    r"\bfix (it|this|the bug)\b",
    r"\bcheck (the )?code\b",
    r"\bdebug\b",
    r"\blook into\b",
    r"\binspect\b",
    r"\breview\b",
    r"\bnot sure\b",
    r"\bunknown\b",
    r"\bn/a\b",
]
UNSAFE_COMPLEXITY = {"unsafe_to_autofix", "destructive", "needs_project_context"}
GENERIC_DIAGNOSIS_VALUES = {"", "unknown", "n/a", "none", "null", "llm_diagnosis"}
GENERIC_FIX_TEXT = {
    "",
    "review the error and code context before changing code.",
    "review the local model diagnosis before changing code.",
    "fix it.",
    "fix the issue.",
}
COMMON_ERROR_TARGETS = {
    "ModuleNotFoundError": {
        "root_cause": "missing_dependency_or_import_path",
        "likely_root_cause": "The required module is missing from the active environment or the import path is incorrect.",
        "suggested_fix": "Install the missing package in the active environment or correct the import path/module name.",
        "confidence": 88,
    },
    "NameError": {
        "root_cause": "undefined_variable_or_missing_import",
        "likely_root_cause": "The code references a name that has not been defined or imported before use.",
        "suggested_fix": "Define the missing variable, import the missing symbol, or correct the misspelled name before using it.",
        "confidence": 86,
    },
    "TypeError": {
        "root_cause": "wrong_type_or_callable_mismatch",
        "likely_root_cause": "A value is being used with the wrong type, wrong call signature, or incompatible operation.",
        "suggested_fix": "Check the value type and call signature, then convert the value or adjust the call to match the expected API.",
        "confidence": 84,
    },
    "FileNotFoundError": {
        "root_cause": "missing_file_or_invalid_path",
        "likely_root_cause": "The code is trying to read or open a file path that does not exist in the current environment.",
        "suggested_fix": "Create the missing file, correct the file path, or resolve the path relative to the project/runtime directory.",
        "confidence": 88,
    },
    "KeyError": {
        "root_cause": "missing_dict_key_or_bad_data_shape",
        "likely_root_cause": "The code expects a dictionary key that is absent because the input data shape is different than expected.",
        "suggested_fix": "Validate the dictionary structure, check that the key exists, or use a safe fallback for missing data.",
        "confidence": 84,
    },
    "SyntaxError": {
        "root_cause": "invalid_python_syntax",
        "likely_root_cause": "The Python source contains invalid syntax that prevents the interpreter from parsing the file.",
        "suggested_fix": "Fix the invalid Python syntax at the reported line before running the file again.",
        "confidence": 90,
    },
    "JSONDecodeError": {
        "root_cause": "invalid_or_empty_json",
        "likely_root_cause": "The JSON parser received empty or invalid JSON content that cannot be decoded.",
        "suggested_fix": "Validate that the input is non-empty valid JSON before calling json.loads or json.load.",
        "confidence": 88,
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare GhostFix Brain v4 LoRA dataset.")
    parser.add_argument("--val-ratio", type=float, default=0.10, help="Validation split ratio. Default: 0.10")
    parser.add_argument("--max-records", type=int, default=0, help="Optional cap for quick dry runs.")
    parser.add_argument("--source", action="append", default=[], help="Additional or replacement JSONL source path.")
    args = parser.parse_args()

    sources = [Path(item) for item in args.source] if args.source else DEFAULT_SOURCES
    result = build_dataset(sources=sources, val_ratio=args.val_ratio, max_records=args.max_records or None)
    write_outputs(result)
    print(
        f"Brain v4 LoRA dataset ready: train={len(result['train'])}, "
        f"val={len(result['val'])}, rejected={sum(result['rejected'].values())}"
    )
    print(f"Wrote {TRAIN_OUT}")
    print(f"Wrote {VAL_OUT}")
    print(f"Wrote {REPORT_OUT}")


def build_dataset(
    *,
    sources: list[Path],
    val_ratio: float = 0.10,
    max_records: int | None = None,
    include_json_only_examples: bool | None = None,
) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    seen: set[str] = set()
    source_counts: Counter[str] = Counter()
    read_count = 0

    for source in sources:
        for raw in _read_jsonl(source):
            read_count += 1
            source_counts[source.as_posix()] += 1
            record, reason, dedupe_key = _convert_record(raw)
            if reason:
                rejected[reason] += 1
                continue
            if dedupe_key in seen:
                rejected["duplicate_near_identical"] += 1
                continue
            seen.add(dedupe_key)
            accepted.append(record)
            if max_records and len(accepted) >= max_records:
                break
        if max_records and len(accepted) >= max_records:
            break

    if include_json_only_examples is None:
        include_json_only_examples = sources == DEFAULT_SOURCES
    if include_json_only_examples:
        for record in _short_json_only_examples():
            accepted.append(record)
            if max_records and len(accepted) >= max_records:
                break

    train, val = _split_without_leakage(accepted, val_ratio)
    return {
        "train": train,
        "val": val,
        "rejected": rejected,
        "read_count": read_count,
        "source_counts": source_counts,
    }


def write_outputs(result: dict[str, Any]) -> None:
    TRAIN_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(TRAIN_OUT, result["train"])
    _write_jsonl(VAL_OUT, result["val"])
    REPORT_OUT.write_text(_report_markdown(result), encoding="utf-8")


def _convert_record(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str]:
    terminal_error = str(raw.get("error") or raw.get("message") or "").strip()
    context = str(raw.get("context") or "").strip()
    failing_line = str(raw.get("failing_line") or "").strip()
    error_type = str(raw.get("error_type") or "").strip()
    cause = _clean_text(raw.get("cause"))
    fix = _clean_text(raw.get("fix"))

    if not _has_terminal_error_signal(terminal_error):
        return None, "missing_traceback_or_terminal_error", ""
    if not context and not failing_line:
        return None, "missing_context", ""
    if not error_type:
        return None, "missing_error_type", ""
    if not cause:
        return None, "missing_root_cause", ""
    if not fix:
        return None, "missing_fix", ""
    if _is_vague_fix(fix):
        return None, "vague_fix", ""
    if _looks_mojibake(fix):
        return None, "garbled_fix_text", ""

    safe_to_autofix = _safe_to_autofix(raw)
    if bool(raw.get("auto_fix_allowed")) and not safe_to_autofix:
        return None, "unsafe_autofix_not_clearly_labeled", ""

    language = _detect_language(raw)
    framework = _detect_framework(raw, language)
    target = _diagnosis_target(raw, error_type, cause, fix, safe_to_autofix)
    evidence = _evidence(raw, terminal_error, context, failing_line)
    output = _compact_json_output({
        "language": language,
        "framework": framework,
        "error_type": error_type,
        "root_cause": target["root_cause"],
        "likely_root_cause": target["likely_root_cause"],
        "evidence": evidence,
        "suggested_fix": target["suggested_fix"],
        "confidence": target["confidence"],
        "safe_to_autofix": safe_to_autofix,
    })

    if _generic_target_output(output):
        return None, "generic_target_output", ""
    if not _valid_output(output):
        return None, "invalid_output_json", ""

    input_text = _build_input(
        terminal_error=terminal_error,
        language=language,
        framework=framework,
        context=context,
        failing_line=failing_line,
        raw=raw,
    )
    lora_record = {
        "instruction": INSTRUCTION,
        "input": input_text,
        "output": output,
    }
    if _contains_forbidden_training_pattern(lora_record):
        return None, "forbidden_training_pattern", ""
    dedupe_key = _dedupe_key(terminal_error, context, error_type)
    return lora_record, "", dedupe_key


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _build_input(
    *,
    terminal_error: str,
    language: str,
    framework: str,
    context: str,
    failing_line: str,
    raw: dict[str, Any],
) -> str:
    hints = {
        "source": raw.get("source") or raw.get("original_source") or "",
        "complexity_class": raw.get("complexity_class") or "",
        "requires_project_context": bool(raw.get("requires_project_context")),
        "auto_fix_allowed_label": bool(raw.get("auto_fix_allowed")),
        "auto_fix_allowed_safe_label": bool(raw.get("auto_fix_allowed_safe")),
    }
    return "\n".join(
        [
            f"language: {language}",
            f"framework: {framework}",
            f"error_type: {raw.get('error_type') or ''}",
            f"failing_line: {failing_line}",
            "context:",
            context,
            "metadata:",
            json.dumps(hints, ensure_ascii=False, sort_keys=True),
            "error_log:",
            terminal_error,
        ]
    ).strip()


def _split_without_leakage(records: list[dict[str, Any]], val_ratio: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    val_ratio = max(0.01, min(0.50, val_ratio))
    train: list[dict[str, Any]] = []
    val: list[dict[str, Any]] = []
    for record in records:
        key = _dedupe_key(record["input"], "", _output_dict(record["output"]).get("error_type", ""))
        bucket = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
        if bucket < val_ratio:
            val.append(record)
        else:
            train.append(record)
    return train, val


def _safe_to_autofix(raw: dict[str, Any]) -> bool:
    complexity = str(raw.get("complexity_class") or "").strip()
    if complexity in UNSAFE_COMPLEXITY:
        return False
    return (
        bool(raw.get("auto_fix_allowed"))
        and bool(raw.get("auto_fix_allowed_safe"))
        and complexity == "deterministic_safe"
    )


def _has_terminal_error_signal(text: str) -> bool:
    lowered = (text or "").lower()
    if not lowered.strip():
        return False
    markers = (
        "traceback",
        "error:",
        "exception",
        "fatal error",
        "parse error",
        "warning:",
        "referenceerror",
        "typeerror",
        "syntaxerror",
        "modulenotfounderror",
        "cannot find module",
        "err_module_not_found",
    )
    return any(marker in lowered for marker in markers)


def _detect_language(raw: dict[str, Any]) -> str:
    text = "\n".join(str(raw.get(key) or "") for key in ("language", "error", "message", "context")).lower()
    if "javascript" in text or "referenceerror" in text and ".js" in text:
        return "javascript"
    if "php " in text or ".php" in text:
        return "php"
    if "java.lang." in text or ".java" in text:
        return "java"
    return "python"


def _detect_framework(raw: dict[str, Any], language: str) -> str:
    text = "\n".join(str(raw.get(key) or "") for key in ("framework", "error", "message", "context", "source_url")).lower()
    if "django" in text:
        return "django"
    if "flask" in text or "jinja2" in text:
        return "flask"
    if "fastapi" in text or "uvicorn" in text:
        return "fastapi"
    if language == "javascript":
        if "next" in text:
            return "nextjs"
        if "vite" in text:
            return "vite"
        if "react" in text:
            return "react"
        return "node"
    if language in {"php", "java"}:
        return language
    return "python"


def _root_cause_label(raw: dict[str, Any], error_type: str, cause: str) -> str:
    explicit = str(raw.get("root_cause") or "").strip()
    if explicit:
        return _slug(explicit)
    if raw.get("hard_negative_v2"):
        task = raw["hard_negative_v2"].get("task") or "hard_negative"
        return _slug(f"{error_type}_{task}_correction")
    label = cause.split(".")[0]
    return _slug(f"{error_type}_{label}")[:80].strip("_") or _slug(error_type)


def _evidence(raw: dict[str, Any], terminal_error: str, context: str, failing_line: str) -> list[str]:
    evidence = []
    file_match = re.search(r'File "([^"]+)", line (\d+)', terminal_error)
    if file_match:
        evidence.append(f"Traceback points to {file_match.group(1)} line {file_match.group(2)}.")
    if failing_line:
        evidence.append(f"Failing line: {failing_line}")
    elif context:
        evidence.append(f"Code context: {context[:240]}")
    error_line = _last_nonempty_line(terminal_error)
    if error_line:
        evidence.append(f"Terminal error: {error_line}")
    return evidence[:4]


def _confidence(raw: dict[str, Any], safe_to_autofix: bool) -> int:
    value = raw.get("quality_score", raw.get("confidence", 80))
    if isinstance(value, str):
        mapped = {"low": 45, "medium": 72, "high": 88}
        numeric = mapped.get(value.lower(), 70)
    else:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 70
        if numeric <= 10:
            numeric *= 10
    if safe_to_autofix:
        numeric = max(numeric, 90)
    return max(0, min(100, int(round(numeric))))


def _diagnosis_target(
    raw: dict[str, Any],
    error_type: str,
    cause: str,
    fix: str,
    safe_to_autofix: bool,
) -> dict[str, Any]:
    common = COMMON_ERROR_TARGETS.get(error_type)
    if common:
        return {
            "root_cause": common["root_cause"],
            "likely_root_cause": _specific_likely_root_cause(error_type, cause, str(common["likely_root_cause"])),
            "suggested_fix": _specific_suggested_fix(error_type, fix, str(common["suggested_fix"])),
            "confidence": _common_confidence(raw, int(common["confidence"]), safe_to_autofix),
        }
    confidence = _confidence(raw, safe_to_autofix)
    if _needs_context(raw):
        confidence = min(confidence, 65)
    elif confidence < 70:
        confidence = 70
    return {
        "root_cause": _root_cause_label(raw, error_type, cause),
        "likely_root_cause": _sentence_or_default(cause, f"The {error_type} indicates the code hit a runtime condition that needs targeted review."),
        "suggested_fix": _sentence_or_default(fix, "Review the failing line, validate the inputs, and apply the smallest targeted correction."),
        "confidence": confidence,
    }


def _specific_likely_root_cause(error_type: str, cause: str, fallback: str) -> str:
    cause = _clean_text(cause)
    if cause and not _generic_text(cause):
        return _sentence_or_default(cause, fallback)
    return fallback


def _specific_suggested_fix(error_type: str, fix: str, fallback: str) -> str:
    fix = _clean_text(fix)
    if fix and not _generic_fix(fix):
        return _sentence_or_default(fix, fallback)
    return fallback


def _common_confidence(raw: dict[str, Any], base: int, safe_to_autofix: bool) -> int:
    if safe_to_autofix:
        return max(base, 90)
    if _needs_context(raw):
        return max(50, min(65, base - 22))
    return max(80, min(90, base))


def _needs_context(raw: dict[str, Any]) -> bool:
    complexity = str(raw.get("complexity_class") or "").strip().lower()
    return bool(raw.get("requires_project_context")) or complexity in {"needs_project_context", "needs_context_reasoning"}


def _sentence_or_default(text: str, default: str) -> str:
    text = _clean_text(text)
    if not text:
        return default
    if text[-1] not in ".!?":
        text += "."
    return text


def _generic_target_output(output: str | dict[str, Any]) -> bool:
    value = _output_dict(output)
    if _generic_text(value.get("root_cause")):
        return True
    if _generic_text(value.get("likely_root_cause")):
        return True
    if _generic_fix(str(value.get("suggested_fix") or "")):
        return True
    return False


def _generic_text(value: Any) -> bool:
    text = str(value or "").strip().lower().strip(".!?")
    return text in GENERIC_DIAGNOSIS_VALUES


def _generic_fix(value: str) -> bool:
    text = str(value or "").strip().lower()
    return text in GENERIC_FIX_TEXT or _is_vague_fix(value)


def _valid_output(output: str | dict[str, Any]) -> bool:
    output = _output_dict(output)
    if not _matches_brain_v4_json_schema(output):
        return False
    try:
        json.loads(_compact_json_output(output))
    except (TypeError, ValueError):
        return False
    return True


def _matches_brain_v4_json_schema(output: dict[str, Any]) -> bool:
    schema = BRAIN_V4_JSON_SCHEMA
    if schema["additionalProperties"] is False and set(output) != set(schema["required"]):
        return False
    for key in schema["required"]:
        if key not in output:
            return False
    for key, rules in schema["properties"].items():
        value = output.get(key)
        expected_type = rules["type"]
        if expected_type == "string":
            if not isinstance(value, str) or len(value.strip()) < int(rules.get("minLength", 0)):
                return False
        elif expected_type == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                return False
            if value < int(rules.get("minimum", value)) or value > int(rules.get("maximum", value)):
                return False
        elif expected_type == "boolean":
            if not isinstance(value, bool):
                return False
        elif expected_type == "array":
            if not isinstance(value, list) or len(value) < int(rules.get("minItems", 0)):
                return False
            item_type = rules.get("items", {}).get("type")
            if item_type == "string" and not all(isinstance(item, str) and item.strip() for item in value):
                return False
    return True


def _compact_json_output(output: dict[str, Any]) -> str:
    return json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _output_dict(output: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(output, str):
        try:
            value = json.loads(output)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return output if isinstance(output, dict) else {}


def _contains_forbidden_training_pattern(record: dict[str, Any]) -> bool:
    text = json.dumps(record, ensure_ascii=False).lower()
    return any(pattern in text for pattern in FORBIDDEN_TRAINING_PATTERNS)


def _is_vague_fix(fix: str) -> bool:
    stripped = fix.strip()
    if len(stripped) < 18:
        return True
    lowered = stripped.lower()
    if any(re.search(pattern, lowered) for pattern in VAGUE_FIX_PATTERNS) and len(stripped) < 80:
        return True
    return False


def _looks_mojibake(text: str) -> bool:
    if "�" in text:
        return True
    suspicious_chars = sum(1 for char in text if char in {"ì", "í", "ë", "ð", "þ", "ã"})
    non_ascii = sum(1 for char in text if ord(char) > 127)
    if suspicious_chars >= 2:
        return True
    return len(text) > 40 and non_ascii / max(len(text), 1) > 0.20


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _dedupe_key(error: str, context: str, error_type: str) -> str:
    normalized = re.sub(r'File ".*?", line \d+', 'File "<path>", line <n>', error)
    normalized = re.sub(r"\b\d+\b", "<n>", normalized.lower())
    normalized = re.sub(r"\s+", " ", f"{error_type}\n{normalized}\n{context.lower()}").strip()
    return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()


def _slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_")


def _last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def _report_markdown(result: dict[str, Any]) -> str:
    rows = result["train"] + result["val"]
    language_counts = _output_counts(rows, "language")
    error_counts = _output_counts(rows, "error_type")
    root_counts = _output_counts(rows, "root_cause")
    rejected = result["rejected"]
    return "\n".join(
        [
            "# GhostFix Brain v4 LoRA Dataset Report",
            "",
            f"Total source records read: {result['read_count']}",
            f"Accepted records: {len(rows)}",
            f"Train records: {len(result['train'])}",
            f"Validation records: {len(result['val'])}",
            f"Rejected records: {sum(rejected.values())}",
            "",
            "## Language Distribution",
            "",
            _counter_table(language_counts),
            "",
            "## Error Type Distribution",
            "",
            _counter_table(error_counts, limit=25),
            "",
            "## Root Cause Distribution",
            "",
            _counter_table(root_counts, limit=25),
            "",
            "## Rejected Record Reasons",
            "",
            _counter_table(rejected),
            "",
            "## Source Files",
            "",
            _counter_table(result["source_counts"]),
            "",
            "## Notes",
            "",
            "- This builder prepares supervised instruction records for LoRA fine-tuning.",
            "- It does not train, download, or load any model.",
            "- Validation split is hash-based to avoid near-duplicate leakage.",
            "- `safe_to_autofix` is true only for records clearly labeled deterministic and safe.",
        ]
    )


def _output_counts(rows: list[dict[str, Any]], key: str) -> Counter[str]:
    return Counter(str(_output_dict(row["output"]).get(key) or "unknown") for row in rows)


def _short_json_only_examples() -> list[dict[str, Any]]:
    base_examples = []
    templates = [
        ("TypeError", "python", "python", "value = count + name", "TypeError: unsupported operand type(s) for +", "typeerror_bad_operands", "Operands have incompatible types.", "Convert or validate operands before using them."),
        ("NameError", "python", "python", "print(user_name)", "NameError: name 'user_name' is not defined", "nameerror_undefined_name", "A variable is used before definition.", "Define the variable or correct the name."),
        ("ModuleNotFoundError", "python", "python", "import requests", "ModuleNotFoundError: No module named 'requests'", "modulenotfounderror_missing_dependency", "The dependency is not installed in the active environment.", "Install the dependency in the active environment."),
        ("ImportError", "python", "python", "from app import create_app", "ImportError: cannot import name 'create_app'", "importerror_missing_symbol", "The imported symbol is not exported by the module.", "Export the symbol or update the import."),
        ("SyntaxError", "python", "python", "if ready print('ok')", "SyntaxError: invalid syntax", "syntaxerror_invalid_syntax", "The statement is missing required syntax.", "Correct the statement syntax."),
        ("IndentationError", "python", "python", "def run():\nprint('ok')", "IndentationError: expected an indented block", "indentationerror_missing_indent", "A block is not indented correctly.", "Indent the block consistently."),
        ("KeyError", "python", "python", "value = data['email']", "KeyError: 'email'", "keyerror_missing_key", "The dictionary key is absent.", "Check for the key before accessing it."),
        ("IndexError", "python", "python", "item = rows[3]", "IndexError: list index out of range", "indexerror_out_of_range", "The list index is outside the available range.", "Check list length before indexing."),
        ("AttributeError", "python", "python", "user.email.lower()", "AttributeError: 'NoneType' object has no attribute 'email'", "attributeerror_none_value", "A None value is used like an object.", "Handle None before accessing attributes."),
        ("ValueError", "python", "python", "int(raw_id)", "ValueError: invalid literal for int()", "valueerror_invalid_conversion", "The value cannot be converted to the requested type.", "Validate or sanitize the value before conversion."),
        ("FileNotFoundError", "python", "python", "open('config.yml')", "FileNotFoundError: [Errno 2] No such file or directory", "filenotfounderror_missing_file", "The file path does not exist.", "Create the file or correct the path."),
        ("ZeroDivisionError", "python", "python", "ratio = total / count", "ZeroDivisionError: division by zero", "zerodivisionerror_zero_denominator", "The denominator is zero.", "Check for zero before dividing."),
        ("JSONDecodeError", "python", "python", "json.loads(body)", "json.decoder.JSONDecodeError: Expecting value", "jsondecodeerror_invalid_json", "The input is not valid JSON.", "Validate the JSON string before parsing."),
        ("TemplateNotFound", "python", "flask", "render_template('home.html')", "jinja2.exceptions.TemplateNotFound: home.html", "templatenotfound_missing_template", "The template file is not available to Flask.", "Place the template in the templates folder or fix the name."),
        ("OperationalError", "python", "django", "User.objects.count()", "django.db.utils.OperationalError: no such table", "operationalerror_missing_table", "The database table has not been created.", "Run migrations for the active database."),
        ("ValidationError", "python", "fastapi", "Item(id='abc')", "pydantic_core._pydantic_core.ValidationError", "validationerror_invalid_field", "Input data does not match the expected schema.", "Fix the input type or schema."),
        ("ReferenceError", "javascript", "node", "console.log(user.name)", "ReferenceError: user is not defined", "referenceerror_undefined_variable", "A variable is referenced before declaration.", "Declare the variable or correct the reference."),
        ("TypeError", "javascript", "react", "items.map(renderItem)", "TypeError: Cannot read properties of undefined", "typeerror_undefined_value", "An undefined value is used like an object or array.", "Initialize the value or guard before access."),
        ("Error", "javascript", "node", "require('express')", "Error: Cannot find module 'express'", "error_missing_node_module", "The Node dependency is missing.", "Install the package in the project environment."),
        ("ERR_MODULE_NOT_FOUND", "javascript", "node", "import app from './app.js'", "Error [ERR_MODULE_NOT_FOUND]: Cannot find module", "err_module_not_found_bad_import", "The module path cannot be resolved.", "Fix the import path or file extension."),
    ]
    for index in range(720):
        error_type, language, framework, context, terminal, root_cause, cause, fix = templates[index % len(templates)]
        sample_id = index + 1
        sample_label = f"seed_case_{chr(97 + (index % 26))}{chr(97 + ((index // 26) % 26))}"
        sample_context = f"{context}\n# {sample_label}"
        sample_terminal = f"{terminal} in {sample_label}"
        input_text = f"Traceback\n  File \"{sample_label}.py\", line 1\n{sample_context}\n{sample_terminal}"
        target = _diagnosis_target({}, error_type, cause, fix, False)
        output = _compact_json_output({
            "language": language,
            "framework": framework,
            "error_type": error_type,
            "root_cause": target["root_cause"],
            "likely_root_cause": target["likely_root_cause"],
            "evidence": [sample_terminal],
            "suggested_fix": target["suggested_fix"],
            "confidence": target["confidence"],
            "safe_to_autofix": False,
        })
        if _valid_output(output):
            base_examples.append({"instruction": SCHEMA_ONLY_INSTRUCTION, "input": input_text, "output": output})
    examples = []
    for _ in range(SCHEMA_ONLY_DUPLICATES):
        examples.extend(base_examples)
    return examples


def _counter_table(counter: Counter[str], limit: int | None = None) -> str:
    if not counter:
        return "| Value | Count |\n|---|---:|\n| none | 0 |"
    lines = ["| Value | Count |", "|---|---:|"]
    for value, count in counter.most_common(limit):
        lines.append(f"| `{value}` | {count} |")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
