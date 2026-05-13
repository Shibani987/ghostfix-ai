from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable


LOCAL_MODEL_ENV = "GHOSTFIX_LOCAL_MODEL_PATH"
REQUIRED_KEYS = {
    "language",
    "framework",
    "error_type",
    "root_cause",
    "likely_root_cause",
    "evidence",
    "suggested_fix",
    "confidence",
    "safe_to_autofix",
}


def build_prompt(
    *,
    language: str,
    framework: str = "",
    terminal_error: str,
    parsed_error: dict[str, Any] | None = None,
    failing_file: str = "",
    failing_line: int | str | None = None,
    code_context: str = "",
    project_context_summary: str = "",
    retriever_matches: Iterable[dict[str, Any]] | None = None,
) -> str:
    """Build the local-only reasoning prompt expected by a code instruct model."""
    parsed = parsed_error or {}
    matches = list(retriever_matches or [])[:3]
    matches_text = json.dumps(matches, ensure_ascii=True, indent=2)
    schema = {
        "language": "python|javascript|java|php|unknown",
        "framework": "django|flask|fastapi|react|vite|nextjs|node|php|java|unknown",
        "error_type": "string",
        "root_cause": "stable_machine_label",
        "likely_root_cause": "human-readable explanation",
        "evidence": ["specific evidence from terminal/code context"],
        "suggested_fix": "conservative suggested fix",
        "confidence": 0,
        "safe_to_autofix": False,
    }
    return f"""You are GhostFix, a local-first terminal error diagnosis assistant.
Use deterministic evidence from the terminal output and code context. Do not invent files or dependencies.
Return ONLY strict JSON matching this schema:
{json.dumps(schema, ensure_ascii=True, indent=2)}

Rules:
- Confidence must be an integer from 0 to 100.
- safe_to_autofix must be false unless a deterministic existing GhostFix rule would safely patch it.
- Prefer a concrete root_cause label and a readable likely_root_cause.
- For React/Vite/Next.js, Node, Java, PHP, and unknown errors, diagnose only; do not propose auto-fix.

LANGUAGE:
{language or "unknown"}

FRAMEWORK:
{framework or "unknown"}

PARSED_ERROR_TYPE:
{parsed.get("type") or parsed.get("error_type") or ""}

PARSED_ERROR_MESSAGE:
{parsed.get("message") or ""}

FAILING_FILE:
{failing_file or parsed.get("file") or ""}

FAILING_LINE:
{failing_line if failing_line not in (None, "") else parsed.get("line") or ""}

CODE_CONTEXT:
{code_context or ""}

PROJECT_CONTEXT_SUMMARY:
{project_context_summary or ""}

RETRIEVER_MATCHES:
{matches_text}

TERMINAL_ERROR:
{terminal_error or parsed.get("raw") or ""}
"""


def diagnose_with_local_llm(
    *,
    language: str,
    framework: str = "",
    terminal_error: str,
    parsed_error: dict[str, Any] | None = None,
    failing_file: str = "",
    failing_line: int | str | None = None,
    code_context: str = "",
    project_context_summary: str = "",
    retriever_matches: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    model_path = _configured_model_path()
    if not model_path:
        return None

    prompt = build_prompt(
        language=language,
        framework=framework,
        terminal_error=terminal_error,
        parsed_error=parsed_error,
        failing_file=failing_file,
        failing_line=failing_line,
        code_context=code_context,
        project_context_summary=project_context_summary,
        retriever_matches=retriever_matches,
    )

    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            str(model_path),
            local_files_only=True,
            trust_remote_code=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            str(model_path),
            local_files_only=True,
            trust_remote_code=True,
        )
        inputs = tokenizer(prompt, return_tensors="pt")
        output_ids = model.generate(
            **inputs,
            max_new_tokens=512,
            do_sample=False,
            pad_token_id=getattr(tokenizer, "eos_token_id", None),
        )
        prompt_length = inputs["input_ids"].shape[-1]
        generated = tokenizer.decode(output_ids[0][prompt_length:], skip_special_tokens=True)
        return parse_llm_json(generated)
    except Exception:
        return None


def diagnose_terminal_output(
    output: str,
    *,
    command: str = "",
    cwd: str | None = None,
    language: str = "unknown",
    framework: str = "unknown",
) -> dict[str, Any] | None:
    from core.project_context import scan_project_context

    project_context = scan_project_context(cwd, command=command)
    result = diagnose_with_local_llm(
        language=language,
        framework=framework,
        terminal_error=output,
        parsed_error={"raw": output, "type": "", "message": _last_nonempty_line(output)},
        project_context_summary=project_context.summary(),
    )
    if not result:
        return None
    return to_diagnostic_schema(result)


def to_diagnostic_schema(result: dict[str, Any]) -> dict[str, Any]:
    confidence = _clamp_confidence(result.get("confidence", 0))
    evidence = result.get("evidence")
    if isinstance(evidence, list):
        evidence_text = "; ".join(str(item) for item in evidence if str(item).strip())
    else:
        evidence_text = str(evidence or "")
    return {
        "language": str(result.get("language") or "unknown"),
        "error_type": str(result.get("error_type") or "UnknownError"),
        "message": str(result.get("message") or ""),
        "file": str(result.get("file") or ""),
        "line": int(result.get("line") or 0) if str(result.get("line") or "").isdigit() else 0,
        "framework": str(result.get("framework") or "unknown"),
        "root_cause": str(result.get("root_cause") or "llm_diagnosis"),
        "likely_root_cause": str(result.get("likely_root_cause") or evidence_text or "The local model identified a likely cause."),
        "suggested_fix": str(result.get("suggested_fix") or "Review the local model diagnosis before changing code."),
        "confidence": confidence,
        "source": "local_llm",
        "auto_fix_available": False,
        "safety_reason": "Auto-fix is disabled for local LLM diagnoses.",
    }


def parse_llm_json(text: str) -> dict[str, Any] | None:
    payload = _extract_json_object(text or "")
    if not payload:
        return None
    try:
        result = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(result, dict) or not REQUIRED_KEYS.issubset(result):
        return None

    result["language"] = str(result.get("language") or "unknown")
    result["framework"] = str(result.get("framework") or "unknown")
    result["error_type"] = str(result.get("error_type") or "UnknownError")
    result["root_cause"] = str(result.get("root_cause") or "llm_diagnosis")
    result["likely_root_cause"] = str(result.get("likely_root_cause") or "")
    result["suggested_fix"] = str(result.get("suggested_fix") or "")
    result["confidence"] = _clamp_confidence(result.get("confidence", 0))
    result["safe_to_autofix"] = bool(result.get("safe_to_autofix")) is True
    if not isinstance(result.get("evidence"), list):
        result["evidence"] = [str(result.get("evidence") or "")]
    return result


def _configured_model_path() -> Path | None:
    raw_path = os.getenv(LOCAL_MODEL_ENV, "").strip()
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    if not path.exists():
        return None
    return path


def _extract_json_object(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start : end + 1]


def _clamp_confidence(value: Any) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, int(round(numeric))))


def _last_nonempty_line(text: str) -> str:
    for line in reversed((text or "").splitlines()):
        if line.strip():
            return line.strip()
    return ""
