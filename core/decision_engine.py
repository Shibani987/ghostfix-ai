from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict
from typing import Optional

from core.confidence import confidence_percent, normalize_confidence
from core.memory import search_memory
from core.safety_policy import evaluate_auto_fix_policy


AUTO_FIX_SAFE_TYPES = {"JSONDecodeError", "SyntaxError", "IndentationError"}
AUTO_FIX_DENY_TYPES = {"NameError", "FileNotFoundError", "KeyError", "IndexError"}
FORCE_BRAIN_V4_ENV = "GHOSTFIX_FORCE_BRAIN_V4"
SAVE_BRAIN_DEBUG_ENV = "GHOSTFIX_SAVE_BRAIN_DEBUG"
BRAIN_MODE_ENV = "GHOSTFIX_BRAIN_MODE"


@dataclass
class Decision:
    status: str
    error_type: Optional[str]
    cause: Optional[str]
    fix: Optional[str]
    confidence: float
    source: str
    auto_fix_available: bool
    auto_fix_plan: str
    patch: str = ""
    brain_type: str = ""
    brain_fix_template: str = ""
    brain_confidence: float = 0.0
    brain_version: str = "v1"
    brain_flag_active: str = "none"
    complexity_class: str = ""
    auto_fix_safety: str = ""
    guard_applied: bool = False
    brain_ignored_reason: str = ""
    brain_used: bool = False
    brain_escalated: bool = False
    brain_raw_available: bool = False
    brain_output_valid: bool = False
    brain_failure_reason: str = "none"
    brain_guard_reason: str = ""
    brain_generation_seconds: float = 0.0
    brain_debug: Optional[dict] = None
    brain_skipped_reason: str = ""
    decision_source_path: str = ""
    escalation_reason: str = "none"
    safety_policy_reason: str = ""
    manual_review_required: bool = True
    brain_v4_output: Optional[dict] = None
    fix_kind: str = "model_suggested_fix"
    patch_confidence: str = ""
    safety_level: str = ""
    validation: str = ""
    deterministic_validator_result: str = ""
    changed_line_count: int = 0
    compile_validation_result: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _snippet(context) -> str:
    if isinstance(context, dict):
        return context.get("snippet") or ""
    return context or ""


def _failing_line(context) -> str:
    if isinstance(context, dict):
        explicit_line = context.get("failing_line")
        if explicit_line:
            return str(explicit_line)
        line_value = context.get("line")
        if isinstance(line_value, str):
            return line_value
        snippet = context.get("snippet") or ""
        if isinstance(line_value, int) and snippet:
            for snippet_line in str(snippet).splitlines():
                prefix = f"{line_value}:"
                if snippet_line.startswith(prefix):
                    return snippet_line[len(prefix):].strip()
    return ""


def _apply_brain(decision: Decision, brain_result: Optional[dict]) -> Decision:
    if not brain_result:
        return decision
    decision.brain_used = True
    decision.brain_skipped_reason = ""
    decision.brain_version = brain_result.get("brain_version", "v1") or "v1"
    decision.brain_flag_active = brain_result.get("brain_flag_active", "none") or "none"
    decision.brain_type = brain_result.get("error_type", "") or ""
    decision.brain_fix_template = brain_result.get("fix_template", "") or ""
    decision.brain_v4_output = brain_result.get("brain_v4_output")
    decision.brain_raw_available = bool(brain_result.get("brain_raw_available"))
    decision.brain_output_valid = bool(brain_result.get("brain_output_valid"))
    decision.brain_failure_reason = brain_result.get("brain_failure_reason", "none") or "none"
    decision.brain_guard_reason = brain_result.get("brain_guard_reason", "") or ""
    decision.brain_generation_seconds = float(brain_result.get("brain_generation_seconds") or 0.0)
    decision.brain_debug = brain_result.get("brain_debug")
    decision.complexity_class = brain_result.get("complexity_class", "") or ""
    decision.auto_fix_safety = brain_result.get("auto_fix_safety", "") or ""
    decision.guard_applied = bool(brain_result.get("guard_applied"))
    try:
        decision.brain_confidence = normalize_confidence(brain_result.get("confidence", 0))
    except (TypeError, ValueError):
        decision.brain_confidence = 0.0
    if _brain_conflicts_at_low_confidence(decision):
        decision.brain_ignored_reason = (
            f"Brain prediction ignored: low-confidence {decision.brain_type} conflicts with parsed {decision.error_type}."
        )
        decision.brain_type = ""
        decision.brain_fix_template = ""
        decision.complexity_class = ""
        decision.auto_fix_safety = ""
        decision.guard_applied = False
        return decision
    if decision.auto_fix_safety in {"not_safe", "unsafe"}:
        decision.auto_fix_available = False
        decision.auto_fix_plan = f"Brain {decision.brain_version} safety metadata marked this case not safe for auto-fix."
        decision.safety_policy_reason = decision.auto_fix_plan
        decision.manual_review_required = True
    return decision


def _brain_conflicts_at_low_confidence(decision: Decision) -> bool:
    if not decision.brain_type or not decision.error_type:
        return False
    return decision.brain_confidence < 0.75 and decision.brain_type != decision.error_type


def apply_safety_policy(
    decision: Decision,
    patch_available: bool = False,
    patch_valid: bool = False,
    fix_kind: str = "model_suggested_fix",
    validation: str = "",
    changed_line_count: int = 0,
    deterministic_validator_result: str = "",
    compile_validation_result: str = "",
) -> Decision:
    decision.fix_kind = fix_kind
    decision.validation = validation
    decision.changed_line_count = changed_line_count
    decision.deterministic_validator_result = deterministic_validator_result
    decision.compile_validation_result = compile_validation_result
    policy = evaluate_auto_fix_policy(
        error_type=decision.error_type,
        complexity_class=decision.complexity_class or ("deterministic_safe" if decision.auto_fix_available else ""),
        confidence=decision.confidence,
        patch_available=patch_available,
        patch_valid=patch_valid,
        brain_auto_fix_safety=decision.auto_fix_safety,
        fix_kind=fix_kind,
    )
    decision.auto_fix_available = policy.auto_fix_allowed
    decision.safety_policy_reason = policy.reason
    decision.manual_review_required = policy.manual_review_required
    if policy.auto_fix_allowed and fix_kind == "deterministic_verified_fix":
        decision.complexity_class = "deterministic_safe"
        decision.patch_confidence = "verified"
        decision.safety_level = "deterministic_safe"
        decision.validation = validation or "ast.parse + compile passed"
        decision.deterministic_validator_result = deterministic_validator_result or "passed"
        decision.compile_validation_result = compile_validation_result or "passed"
    if not policy.auto_fix_allowed:
        decision.auto_fix_plan = policy.reason
    return decision


def _base_decision(
    parsed_error: dict,
    cause: str,
    fix: str,
    confidence: int | float,
    source: str,
) -> Decision:
    error_type = parsed_error.get("type")
    auto_fix_available = error_type in AUTO_FIX_SAFE_TYPES and error_type not in AUTO_FIX_DENY_TYPES
    auto_fix_plan = "No safe auto-fix is available for this error type."

    if error_type == "JSONDecodeError":
        auto_fix_plan = "Guard json.loads(...) with an empty-input check and preserve the assigned variable."
    elif error_type in {"SyntaxError", "IndentationError"}:
        auto_fix_plan = "Only simple syntax fixes are allowed when a deterministic patch can be generated."

    return Decision(
        status="error",
        error_type=error_type,
        cause=cause,
        fix=fix,
        confidence=normalize_confidence(confidence),
        source=source,
        auto_fix_available=auto_fix_available,
        auto_fix_plan=auto_fix_plan,
    )


def decide_fix(parsed_error: Optional[dict], context=None, use_llm: bool = False) -> Decision:
    if not parsed_error:
        return Decision(
            status="success",
            error_type=None,
            cause=None,
            fix=None,
            confidence=1.0,
            source="none",
            auto_fix_available=False,
            auto_fix_plan="No error detected.",
        )

    error_type = parsed_error.get("type", "UnknownError")
    message = parsed_error.get("message", "")

    memory = search_memory(error_type, message)
    package_decision = None
    rule_decision = None
    retriever_decision = None

    if parsed_error.get("missing_package"):
        package = parsed_error["missing_package"]
        package_cause, package_fix = _module_not_found_guidance(package, parsed_error, context)
        package_decision = _base_decision(parsed_error, package_cause, package_fix, 96, "rule")
        package_decision.auto_fix_available = False
        package_decision.auto_fix_plan = "GhostFix can suggest the install command, but will not install packages automatically."

    rule_decision = _rule_decision(parsed_error, context)
    retriever_decision = _retriever_decision(parsed_error, context)
    brain_result = None if _brain_mode() == "off" or _brain_v4_available() else _brain_decision(parsed_error, context)

    if memory:
        decision = _base_decision(
            parsed_error,
            memory.get("cause") or "A similar successful fix was found in memory.",
            memory.get("fix") or "Reuse the previously successful fix.",
            92,
            "hybrid: memory/retriever/brain",
        )
        if rule_decision:
            decision.auto_fix_available = rule_decision.auto_fix_available
            decision.auto_fix_plan = rule_decision.auto_fix_plan
            decision.confidence = max(decision.confidence, rule_decision.confidence)
            if rule_decision.confidence >= 0.95:
                decision.cause = rule_decision.cause
                decision.fix = rule_decision.fix
        return _finish_decision(
            _with_routing(decision, "memory -> rules" if rule_decision else "memory"),
            parsed_error,
            context,
            brain_result,
            deterministic_rule_matched=bool(rule_decision),
        )

    if package_decision:
        package_decision.source = "hybrid: memory/retriever/brain"
        return _finish_decision(_with_routing(package_decision, "rules only"), parsed_error, context, brain_result, deterministic_rule_matched=True)

    if retriever_decision:
        if rule_decision and retriever_decision.confidence < 0.55:
            rule_decision.source = "hybrid: memory/retriever/brain"
            return _finish_decision(_with_routing(rule_decision, "rules only"), parsed_error, context, brain_result, deterministic_rule_matched=True)
        retriever_decision.source = "hybrid: memory/retriever/brain"
        if rule_decision:
            # Deterministic rules own auto-fix availability; retriever only
            # contributes the more specific cause/fix text.
            retriever_decision.auto_fix_available = rule_decision.auto_fix_available
            retriever_decision.auto_fix_plan = rule_decision.auto_fix_plan
            retriever_decision.confidence = max(retriever_decision.confidence, rule_decision.confidence)
            if rule_decision.confidence >= 0.95:
                retriever_decision.cause = rule_decision.cause
                retriever_decision.fix = rule_decision.fix
        route = "rules -> retriever" if rule_decision else "retriever only"
        return _finish_decision(
            _with_routing(retriever_decision, route),
            parsed_error,
            context,
            brain_result,
            deterministic_rule_matched=bool(rule_decision),
        )

    if rule_decision:
        rule_decision.source = "hybrid: memory/retriever/brain"
        return _finish_decision(_with_routing(rule_decision, "rules only"), parsed_error, context, brain_result, deterministic_rule_matched=True)

    local_llm_decision = _local_llm_decision(parsed_error, context)
    if local_llm_decision:
        return _finish_decision(_with_routing(local_llm_decision, "local_llm"), parsed_error, context, brain_result)

    if _brain_is_high_confidence(brain_result):
        decision = _brain_fallback_decision(parsed_error, brain_result)
        return _finish_decision(_with_routing(decision, "brain"), parsed_error, context, brain_result)

    if use_llm:
        llm_decision = _llm_decision(parsed_error, context)
        if llm_decision:
            return _finish_decision(_with_routing(llm_decision, "llm"), parsed_error, context, brain_result)

    decision = _base_decision(
        parsed_error,
        f"Unhandled error type: {error_type}",
        "Inspect the traceback and code context before changing code.",
        20,
        "fallback",
    )
    return _finish_decision(_with_routing(decision, "fallback"), parsed_error, context, brain_result)


def _with_routing(decision: Decision, route: str, escalation_reason: str = "none") -> Decision:
    decision.decision_source_path = route
    decision.escalation_reason = escalation_reason
    return decision


def _finish_decision(
    decision: Decision,
    parsed_error: dict,
    context,
    brain_result: Optional[dict] = None,
    *,
    deterministic_rule_matched: bool = False,
) -> Decision:
    if _brain_v4_available():
        return _apply_brain_v4_gated(decision, parsed_error, context, deterministic_rule_matched)
    return _apply_brain(decision, brain_result)


def _brain_v4_available() -> bool:
    return os.getenv("GHOSTFIX_BRAIN_V4") == "1" and os.getenv(BRAIN_MODE_ENV, "auto") != "off"


def _force_brain_v4() -> bool:
    return os.getenv(FORCE_BRAIN_V4_ENV) == "1"


def _apply_brain_v4_gated(
    decision: Decision,
    parsed_error: dict,
    context,
    deterministic_rule_matched: bool,
) -> Decision:
    should_run, reason, escalation_reason = _should_run_brain_v4(decision, deterministic_rule_matched)
    if not should_run:
        decision.brain_version = "v4-lora"
        decision.brain_flag_active = "GHOSTFIX_BRAIN_V4=1"
        decision.brain_used = False
        decision.brain_skipped_reason = reason
        decision.escalation_reason = "none"
        return decision

    decision.escalation_reason = escalation_reason
    decision.brain_escalated = True
    if decision.decision_source_path:
        decision.decision_source_path = f"{decision.decision_source_path} -> brain"
    else:
        decision.decision_source_path = "brain"
    if _brain_mode() == "route-only":
        decision.brain_used = False
        decision.brain_version = "v4-lora"
        decision.brain_flag_active = "GHOSTFIX_BRAIN_V4=1"
        decision.brain_failure_reason = "route_only"
        decision.brain_guard_reason = "Brain generation skipped by route-only benchmark mode."
        decision.brain_skipped_reason = decision.brain_guard_reason
        return decision
    brain_result = _brain_v4_decision(parsed_error, context)
    if not brain_result or not brain_result.get("usable", True):
        decision.brain_used = False
        decision.brain_version = (brain_result or {}).get("brain_version", "v4-lora") or "v4-lora"
        decision.brain_flag_active = (brain_result or {}).get("brain_flag_active", "GHOSTFIX_BRAIN_V4=1") or "GHOSTFIX_BRAIN_V4=1"
        decision.brain_type = (brain_result or {}).get("error_type", "") or ""
        decision.brain_fix_template = (brain_result or {}).get("fix_template", "") or ""
        decision.brain_v4_output = (brain_result or {}).get("brain_v4_output")
        decision.brain_raw_available = bool((brain_result or {}).get("brain_raw_available"))
        decision.brain_output_valid = bool((brain_result or {}).get("brain_output_valid"))
        decision.brain_failure_reason = (brain_result or {}).get("brain_failure_reason", "unavailable") or "unavailable"
        decision.brain_guard_reason = (brain_result or {}).get("brain_guard_reason", "") or ""
        decision.brain_generation_seconds = float((brain_result or {}).get("brain_generation_seconds") or 0.0)
        decision.brain_debug = (brain_result or {}).get("brain_debug")
        decision.brain_skipped_reason = decision.brain_guard_reason or "Brain v4 unavailable or returned no usable diagnosis."
        return decision

    if _brain_is_high_confidence(brain_result) and (
        decision.source == "fallback" or decision.confidence < 0.55 or _decision_has_generic_guidance(decision)
    ):
        decision = _brain_fallback_decision(parsed_error, brain_result)
        decision.escalation_reason = escalation_reason
        decision.brain_escalated = True
        decision.decision_source_path = "fallback -> brain"
    return _apply_brain(decision, brain_result)


def _should_run_brain_v4(decision: Decision, deterministic_rule_matched: bool) -> tuple[bool, str, str]:
    if _force_brain_v4():
        return True, "", "forced_brain"
    if deterministic_rule_matched:
        return False, "deterministic rule matched", "none"
    if decision.source == "fallback":
        return True, "", "unsupported_error_type"
    if decision.confidence < 0.85:
        return True, "", "low_confidence"
    if _decision_has_generic_guidance(decision):
        return True, "", "missing_specific_cause"
    return False, "existing decision confidence >= 85 with specific cause/fix", "none"


def _brain_mode() -> str:
    mode = os.getenv(BRAIN_MODE_ENV, "auto").strip().lower()
    return mode if mode in {"auto", "off", "route-only", "generate"} else "auto"


def _decision_has_generic_guidance(decision: Decision) -> bool:
    cause = str(decision.cause or "").strip().lower()
    fix = str(decision.fix or "").strip().lower()
    if not cause or not fix:
        return True
    generic_fragments = (
        "unhandled error type",
        "inspect the traceback",
        "inspect the value",
        "review the traceback",
        "review the error",
        "review the matched local example",
        "local model generated an analysis",
    )
    return any(fragment in cause or fragment in fix for fragment in generic_fragments)


def _syntax_missing_colon_cause(failing_line: str) -> Optional[tuple[str, str]]:
    stripped = failing_line.strip()
    if not stripped or stripped.endswith(":"):
        return None
    if stripped.startswith("def "):
        return (
            "The function definition is missing a colon.",
            "Add a colon at the end of the function definition.",
        )
    if stripped.startswith("class "):
        return (
            "The class definition is missing a colon.",
            "Add a colon at the end of the class definition.",
        )
    return None


def _module_not_found_guidance(package: str, parsed_error: dict, context=None) -> tuple[str, str]:
    snippet = _snippet(context).lower()
    failing_line = _failing_line(context).lower()
    package_lower = str(package or "").lower()

    if "django_settings_module" in snippet or "settings" in package_lower:
        return (
            f"The Django settings module import path '{package}' cannot be imported from the active project/environment.",
            "Verify DJANGO_SETTINGS_MODULE, project package names, and Python path before treating this as a pip package.",
        )

    if "fastapi" in snippet or "fastapi" in failing_line or "multipart" in package_lower:
        return (
            f"The FastAPI endpoint imports optional dependency '{package}', but it is not installed in the active environment.",
            f"Install the optional FastAPI dependency in this environment or guard the endpoint import: pip install {package}",
        )

    return (
        f"The Python package '{package}' is not installed in the active environment.",
        f"Install it in the same environment: pip install {package}",
    )


def _contextual_rule_guidance(
    error_type: str,
    parsed_error: dict,
    context=None,
) -> Optional[tuple[str, str, int]]:
    message = parsed_error.get("message") or ""
    raw = parsed_error.get("raw") or ""
    snippet = _snippet(context)
    failing_line = _failing_line(context)
    combined = f"{message}\n{raw}\n{snippet}\n{failing_line}"
    combined_lower = combined.lower()

    if error_type == "KeyError":
        missing_key = _quoted_value(message)
        if missing_key and _looks_like_environment_variable(missing_key):
            return (
                f"The required environment variable '{missing_key}' is missing from the process environment.",
                f"Set {missing_key} before running the app, or read it with validation and a clear configuration error.",
                95,
            )
        if missing_key and (any(marker in combined_lower for marker in ("dataframe", "pd.", "pandas", ".columns", "orders[")) or re.search(r'\[.*\]', failing_line)):
            return (
                f"The pandas DataFrame does not contain the requested '{missing_key}' column.",
                "Validate the DataFrame schema or guard column access before using the missing column.",
                95,
            )

    if error_type == "AttributeError" and "nonetype" in message.lower():
        attribute = _attribute_name(message)
        access_target = _attribute_access_target(failing_line)
        target_text = f" '{access_target}'" if access_target else ""
        attribute_text = f" before accessing '{attribute}'" if attribute else " before attribute access"
        return (
            f"The object{target_text} is None{attribute_text}.",
            "Check for None or handle the missing lookup/result before dereferencing the object.",
            95,
        )

    if error_type == "TypeError" and (
        "positional argument" in message.lower()
        or "keyword-only" in message.lower()
        or "positional arguments" in message.lower()
    ):
        return (
            "The function call uses the wrong signature, passing a positional argument where the function expects a keyword-only parameter.",
            "Call the function with the declared keyword argument or update the function signature intentionally.",
            95,
        )

    if error_type == "IndexError" and (
        "list index out of range" in message.lower()
        or any(marker in combined_lower for marker in ("results[", "api_results[", "list["))
    ):
        return (
            "The result list is empty or shorter than expected before the code indexes into it.",
            "Check that the list has an item at the requested index before accessing it.",
            95,
        )

    if error_type == "FileNotFoundError":
        missing_path = _missing_file_path(message)
        if missing_path:
            return (
                f"The configured file path '{missing_path}' does not exist at runtime.",
                "Verify the path, create the file, or resolve it relative to the intended working directory.",
                95,
            )

    if error_type == "JSONDecodeError" and any(marker in combined_lower for marker in ("response.text", "status_code = 204", "http")):
        return (
            "The code attempts to parse an empty HTTP response body as JSON.",
            "Check that the response body has content before calling json.loads(...).",
            95,
        )

    if error_type == "PermissionError":
        denied_path = _missing_file_path(message)
        if denied_path and any(marker in combined_lower for marker in (".parent", ".open(\"w\"", ".open('w'", "directory")):
            return (
                f"The code attempts to open directory path '{denied_path}' as a writable file target.",
                "Write to a concrete file path inside the directory, and verify permissions before opening it.",
                95,
            )

    return None


def _quoted_value(text: str) -> str:
    match = re.search(r"'([^']+)'", text or "")
    return match.group(1) if match else ""


def _looks_like_environment_variable(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]*", value or ""))


def _attribute_name(text: str) -> str:
    match = re.search(r"has no attribute '([^']+)'", text or "")
    return match.group(1) if match else ""


def _attribute_access_target(line: str) -> str:
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\.", line or "")
    return match.group(1) if match else ""


def _missing_file_path(text: str) -> str:
    quoted = re.findall(r"'([^']+)'", text or "")
    return quoted[-1] if quoted else ""


def _rule_decision(parsed_error: dict, context=None) -> Optional[Decision]:
    error_type = parsed_error.get("type")
    rules = {
        "NameError": (
            "A variable or function is used before it is defined.",
            "Define the missing variable/function before using it, or fix the spelling.",
            82,
        ),
        "FileNotFoundError": (
            "The file path does not exist or the file is missing.",
            "Check the path, create the file, or use an absolute path.",
            86,
        ),
        "SyntaxError": (
            "Python could not parse the file because of invalid syntax.",
            "Check the exact line for a missing colon, unmatched bracket, quote, or indentation issue.",
            78,
        ),
        "IndentationError": (
            "The code block indentation is inconsistent or incomplete.",
            "Align indentation with the surrounding block.",
            78,
        ),
        "KeyError": (
            "The dictionary key does not exist at runtime.",
            "Check the key name or use dict.get('key') with a default value after confirming the data shape.",
            78,
        ),
        "IndexError": (
            "The sequence index is outside the available range.",
            "Check the sequence length before indexing.",
            78,
        ),
        "ZeroDivisionError": (
            "A value is being divided by zero.",
            "Check the denominator before division and handle the zero case.",
            90,
        ),
        "JSONDecodeError": (
            "The code is parsing JSON without first checking that the input has content.",
            "Guard json.loads(...) with an empty-input check before parsing.",
            95,
        ),
        "TypeError": (
            "An operation or function received an incompatible type.",
            "Inspect the value types and convert or validate them before the operation.",
            76,
        ),
        "AttributeError": (
            "The code is accessing an attribute or method that is not available on the runtime value.",
            "Check the value before attribute access, especially for None or unexpected response objects.",
            78,
        ),
        "PermissionError": (
            "The process does not have permission to access the requested file path or mode.",
            "Verify the target path, permissions, and whether the code is opening a directory as a file.",
            82,
        ),
    }

    if error_type not in rules:
        return None

    cause, fix, confidence = rules[error_type]
    contextual = _contextual_rule_guidance(error_type, parsed_error, context)
    if contextual:
        cause, fix, confidence = contextual
    elif error_type == "SyntaxError" and "expected ':'" in (parsed_error.get("message") or ""):
        syntax_cause = _syntax_missing_colon_cause(_failing_line(context))
        if syntax_cause:
            cause, fix = syntax_cause
            confidence = 95
    decision = _base_decision(parsed_error, cause, fix, confidence, "rule")
    if error_type in AUTO_FIX_DENY_TYPES:
        decision.auto_fix_available = False
        decision.auto_fix_plan = "Auto-fix is disabled because this error may require intent or data-shape knowledge."
    return decision


def _retriever_decision(parsed_error: dict, context) -> Optional[Decision]:
    try:
        from ml.retriever_router import predict_fix

        results = predict_fix(
            error_text=parsed_error.get("raw", ""),
            context=_snippet(context),
            language="python",
            top_k=1,
            min_confidence=35.0,
        )
    except Exception as exc:
        if parsed_error.get("verbose"):
            print(f"Retriever skipped: {exc}")
        return None

    if not results:
        return None

    best = results[0]
    return _base_decision(
        parsed_error,
        best.get("cause") or "A similar local training example matched this error.",
        best.get("fix") or "Review the matched local example before changing code.",
        int(float(best.get("confidence", 50))),
        best.get("retriever_backend") or best.get("source") or "retriever",
    )


def _brain_decision(parsed_error: dict, context) -> Optional[dict]:
    if os.getenv("GHOSTFIX_BRAIN_V4") == "1":
        return _brain_v4_decision(parsed_error, context)
    if os.getenv("GHOSTFIX_BRAIN_V33") == "1":
        return _brain_v33_decision(parsed_error, context)
    if os.getenv("GHOSTFIX_BRAIN_V2") == "1":
        return _brain_v2_decision(parsed_error, context)
    return _brain_v1_decision(parsed_error, context)


_BRAIN_V4_RUNTIME = None


def _brain_v4_runtime():
    global _BRAIN_V4_RUNTIME
    if _BRAIN_V4_RUNTIME is None:
        from ml.brain_v4_inference import BrainV4Inference

        _BRAIN_V4_RUNTIME = BrainV4Inference()
    return _BRAIN_V4_RUNTIME


def _brain_v4_decision(parsed_error: dict, context) -> Optional[dict]:
    include_debug = os.getenv(SAVE_BRAIN_DEBUG_ENV) == "1"
    try:
        runner = _brain_v4_runtime()
        result = runner.diagnose(
            terminal_error=parsed_error.get("raw", ""),
            context=_snippet(context),
            language="python",
            framework="python",
            parsed_error=parsed_error,
            include_debug=include_debug,
        )
    except Exception as exc:
        if parsed_error.get("verbose"):
            print(f"GhostFix Brain v4 skipped: {exc}")
        return _unusable_brain_result(_brain_exception_reason(exc), f"Brain v4 exception: {exc}")

    if not result or not result.get("available"):
        if parsed_error.get("verbose"):
            print(f"GhostFix Brain v4 skipped: {result.get('reason') if isinstance(result, dict) else 'unavailable'}")
        reason = str((result or {}).get("reason", "Brain v4 unavailable"))
        failure_reason = "timeout" if "timeout" in reason.lower() else "unavailable"
        return _unusable_brain_result(failure_reason, reason, result)

    diagnosis = result.get("diagnosis")
    if not isinstance(diagnosis, dict):
        return _unusable_brain_result("malformed_output", "Brain v4 did not return a diagnosis object.", result)

    safe_advisory = bool(diagnosis.get("safe_to_autofix"))
    generic_fallback = _brain_v4_is_generic_fallback(diagnosis)
    failure_reason = _classify_brain_v4_result(diagnosis, parsed_error)
    if generic_fallback and failure_reason == "success":
        failure_reason = "generic_response"
    usable = failure_reason == "success"
    return {
        "usable": usable,
        "brain_version": "v4-lora",
        "brain_flag_active": "GHOSTFIX_BRAIN_V4=1",
        "error_type": diagnosis.get("error_type", ""),
        "fix_template": diagnosis.get("suggested_fix", ""),
        "fix_template_text": diagnosis.get("suggested_fix", ""),
        "confidence": diagnosis.get("confidence", 0),
        "auto_fix_safety": "advisory_safe" if safe_advisory else "advisory_not_safe",
        "complexity_class": "",
        "guard_applied": False,
        "generic_fallback": generic_fallback,
        "brain_v4_output": diagnosis,
        "raw_prediction": diagnosis,
        "brain_raw_available": bool(result.get("raw_output")),
        "brain_output_valid": True,
        "brain_failure_reason": failure_reason,
        "brain_guard_reason": "" if usable else failure_reason,
        "brain_debug": _brain_debug_payload(result, diagnosis) if include_debug else None,
        "brain_generation_seconds": float(result.get("generation_seconds") or 0.0),
    }


def _unusable_brain_result(reason: str, guard_reason: str, raw_result: Optional[dict] = None) -> dict:
    raw_result = raw_result or {}
    return {
        "usable": False,
        "brain_version": "v4-lora",
        "brain_flag_active": "GHOSTFIX_BRAIN_V4=1",
        "brain_raw_available": bool(raw_result.get("raw_output")),
        "brain_output_valid": bool(raw_result.get("parsed_output")),
        "brain_failure_reason": reason,
        "brain_guard_reason": guard_reason,
        "brain_generation_seconds": float(raw_result.get("generation_seconds") or 0.0),
        "brain_debug": _brain_debug_payload(raw_result, raw_result.get("diagnosis")) if os.getenv(SAVE_BRAIN_DEBUG_ENV) == "1" else None,
    }


def _brain_exception_reason(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}".lower()
    if "timeout" in text or "timed out" in text:
        return "timeout"
    return "unavailable"


def _classify_brain_v4_result(diagnosis: dict, parsed_error: dict) -> str:
    if not diagnosis:
        return "malformed_output"
    if not diagnosis.get("root_cause") or str(diagnosis.get("root_cause")).strip().lower() == "unknown":
        return "missing_root_cause"
    if _brain_v4_is_generic_fallback(diagnosis):
        return "generic_response"
    try:
        confidence = float(diagnosis.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0
    if confidence < 75:
        return "low_confidence"
    predicted = str(diagnosis.get("error_type") or "")
    actual = str(parsed_error.get("type") or "")
    if predicted and actual and predicted != actual:
        return "wrong_error_type"
    return "success"


def _brain_debug_payload(raw_result: dict, final_output: Optional[dict]) -> dict:
    return {
        "prompt": raw_result.get("prompt", ""),
        "raw_generation": raw_result.get("raw_output", ""),
        "parsed_output": raw_result.get("parsed_output"),
        "normalized_output": raw_result.get("final_output") or final_output,
        "final_normalized_output": raw_result.get("final_output") or final_output,
    }


def _brain_v4_is_generic_fallback(diagnosis: dict) -> bool:
    try:
        confidence = float(diagnosis.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0
    root_cause = str(diagnosis.get("root_cause") or "").strip().lower()
    suggested_fix = str(diagnosis.get("suggested_fix") or "").strip().lower()
    return (
        confidence <= 50
        or root_cause == "unknown"
        or suggested_fix.startswith("review the error")
    )


def _brain_v1_decision(parsed_error: dict, context) -> Optional[dict]:
    try:
        from ml.ghostfix_brain_predict import predict

        result = predict(
            error=parsed_error.get("raw", ""),
            message=parsed_error.get("message", ""),
            context=_snippet(context),
            failing_line=_failing_line(context),
            use_retriever=False,
        )
        result["brain_version"] = "v1"
        result.setdefault("brain_flag_active", "none")
        return result
    except Exception as exc:
        if parsed_error.get("verbose"):
            print(f"GhostFix Brain skipped: {exc}")
        return None


def _brain_v2_decision(parsed_error: dict, context) -> Optional[dict]:
    try:
        from ml.ghostfix_brain_v2_predict import predict_record

        result = predict_record({
            "error": parsed_error.get("raw", ""),
            "message": parsed_error.get("message", ""),
            "context": _snippet(context),
            "failing_line": _failing_line(context),
        })
        guarded = result["guarded_prediction"]
        confidence = result.get("confidence", {})
        auto_fix_safety = guarded.get("auto_fix_safety", "not_safe")
        return {
            "brain_version": "v2 experimental",
            "brain_flag_active": "GHOSTFIX_BRAIN_V2=1",
            "error_type": guarded.get("error_type", ""),
            "fix_template": guarded.get("fix_template", ""),
            "fix_template_text": result.get("fix_template_text", guarded.get("fix_template", "")),
            "complexity_class": guarded.get("complexity", ""),
            "auto_fix_safety": auto_fix_safety,
            "confidence": normalize_confidence(max([float(value) for value in confidence.values()] or [0])),
            "guard_applied": bool(result.get("auto_fix_safety_guard_applied")),
            "guard_reasons": result.get("auto_fix_safety_guard_reasons", []),
            "raw_prediction": result.get("raw_prediction", {}),
        }
    except Exception as exc:
        if parsed_error.get("verbose"):
            print(f"GhostFix Brain v2 skipped: {exc}")
        result = _brain_v1_decision(parsed_error, context)
        if result:
            result["brain_flag_active"] = "GHOSTFIX_BRAIN_V2=1; fallback=v1"
        return result


def _brain_v33_decision(parsed_error: dict, context) -> Optional[dict]:
    try:
        from ml.ghostfix_brain_v33_predict import predict_record

        result = predict_record({
            "error": parsed_error.get("raw", ""),
            "message": parsed_error.get("message", ""),
            "context": _snippet(context),
            "failing_line": _failing_line(context),
        })
        guarded = result["guarded_prediction"]
        confidence = result.get("confidence", {})
        auto_fix_safety = guarded.get("auto_fix_safety", "not_safe")
        guard_reasons = result.get("auto_fix_safety_guard_reasons", [])
        return {
            "brain_version": "v3.3-experimental",
            "brain_flag_active": "GHOSTFIX_BRAIN_V33=1",
            "error_type": guarded.get("error_type", ""),
            "fix_template": guarded.get("fix_template", ""),
            "fix_template_text": result.get("fix_template_text", guarded.get("fix_template", "")),
            "complexity_class": guarded.get("complexity_class", ""),
            "auto_fix_safety": auto_fix_safety,
            "confidence": normalize_confidence(max([float(value) for value in confidence.values()] or [0])),
            "guard_applied": bool(result.get("auto_fix_safety_guard_applied")),
            "guard_reasons": guard_reasons,
            "safety_reason": "; ".join(guard_reasons) if guard_reasons else "",
            "raw_prediction": result.get("raw_prediction", {}),
        }
    except Exception as exc:
        if parsed_error.get("verbose"):
            print(f"GhostFix Brain v3.3 skipped: {exc}")
        result = _brain_v1_decision(parsed_error, context)
        if result:
            result["brain_flag_active"] = "GHOSTFIX_BRAIN_V33=1; fallback=v1"
        return result


def _brain_is_high_confidence(brain_result: Optional[dict]) -> bool:
    if not brain_result:
        return False
    if brain_result.get("generic_fallback"):
        return False
    try:
        return normalize_confidence(brain_result.get("confidence", 0)) >= 0.75
    except (TypeError, ValueError):
        return False


def _brain_fallback_decision(parsed_error: dict, brain_result: dict) -> Decision:
    root_cause = brain_result.get("root_cause")
    if not root_cause and isinstance(brain_result.get("brain_v4_output"), dict):
        root_cause = (
            brain_result["brain_v4_output"].get("likely_root_cause")
            or brain_result["brain_v4_output"].get("root_cause")
        )
    decision = _base_decision(
        parsed_error,
        root_cause or f"GhostFix Brain classified this as {brain_result.get('error_type')} with high confidence.",
        brain_result.get("fix_template_text") or brain_result.get("fix_template") or "Review the traceback and local code context before editing.",
        normalize_confidence(brain_result.get("confidence", 0.60)),
        "hybrid: memory/retriever/brain",
    )
    decision.auto_fix_available = False
    decision.auto_fix_plan = "Brain-only predictions never enable auto-fix; use as diagnosis guidance only."
    return decision


def _local_llm_decision(parsed_error: dict, context) -> Optional[Decision]:
    try:
        from core.local_llm import diagnose_with_local_llm
        from core.project_context import scan_project_context

        project_context = scan_project_context(
            None,
            start_path=parsed_error.get("file") or None,
        )
        result = diagnose_with_local_llm(
            language="python",
            framework="python",
            terminal_error=parsed_error.get("raw", ""),
            parsed_error=parsed_error,
            failing_file=parsed_error.get("file") or "",
            failing_line=parsed_error.get("line") or "",
            code_context=_snippet(context),
            project_context_summary=project_context.summary(),
            retriever_matches=[],
        )
    except Exception:
        return None

    if not result:
        return None

    decision = _base_decision(
        parsed_error,
        result.get("likely_root_cause") or result.get("root_cause") or "The local model generated an analysis.",
        result.get("suggested_fix") or "Review the local model diagnosis before changing code.",
        result.get("confidence", 50),
        "local_llm",
    )
    decision.auto_fix_available = False
    decision.auto_fix_plan = "Local LLM diagnoses never enable auto-fix; safety policy remains the final gate."
    decision.manual_review_required = True
    return decision


def _llm_decision(parsed_error: dict, context) -> Optional[Decision]:
    try:
        from ml.model_inference import generate_fix

        result = generate_fix(parsed_error.get("raw", ""), _snippet(context), use_llm=True)
    except Exception:
        return None

    if not result or result.get("mode") == "retriever_only":
        return None

    return _base_decision(
        parsed_error,
        result.get("cause") or "The local model generated an analysis.",
        result.get("fix") or result.get("response") or "Review the local model response.",
        60,
        "llm",
    )


def format_decision(decision: Decision, patch: str = "") -> str:
    patch_text = patch or ""
    block_reason = "" if decision.auto_fix_available else decision.safety_policy_reason
    confidence_block = f"""MODEL_CONFIDENCE:
{confidence_percent(decision.confidence)}%

DIAGNOSIS_CONFIDENCE:
{confidence_percent(decision.confidence)}%
""" if decision.auto_fix_available else f"""CONFIDENCE:
{confidence_percent(decision.confidence)}%
"""
    patch_validation_block = ""
    if decision.auto_fix_available and decision.fix_kind == "deterministic_verified_fix":
        patch_validation_block = f"""
PATCH_CONFIDENCE:
{decision.patch_confidence or "verified"}

SAFETY_LEVEL:
{decision.safety_level or "deterministic_safe"}

VALIDATION:
{decision.validation or "ast.parse + compile passed"}

DETERMINISTIC_VALIDATOR_RESULT:
{decision.deterministic_validator_result or "passed"}

CHANGED_LINE_COUNT:
{decision.changed_line_count}

COMPILE_VALIDATION_RESULT:
{decision.compile_validation_result or "passed"}
"""
    return f"""STATUS:
{decision.status}

ERROR_TYPE:
{decision.error_type or ""}

CAUSE:
{decision.cause or ""}

FIX:
{decision.fix or ""}

{confidence_block}

SOURCE:
{decision.source}

BRAIN_VERSION:
{decision.brain_version}

BRAIN_FLAG_ACTIVE:
{decision.brain_flag_active}

BRAIN_TYPE:
{decision.brain_type}

BRAIN_FIX_TEMPLATE:
{decision.brain_fix_template}

FIX_TEMPLATE:
{decision.brain_fix_template}

BRAIN_CONFIDENCE:
{confidence_percent(decision.brain_confidence)}%

COMPLEXITY_CLASS:
{decision.complexity_class}

AUTO_FIX_SAFETY:
{decision.auto_fix_safety}

GUARD_APPLIED:
{"yes" if decision.guard_applied else "no"}

BRAIN_IGNORED_REASON:
{decision.brain_ignored_reason}

BRAIN_USED:
{"yes" if decision.brain_used else "no"}

BRAIN_ESCALATED:
{"yes" if decision.brain_escalated else "no"}

BRAIN_FAILURE_REASON:
{decision.brain_failure_reason}

BRAIN_GUARD_REASON:
{decision.brain_guard_reason}

BRAIN_GENERATION_SECONDS:
{decision.brain_generation_seconds}

BRAIN_SKIPPED_REASON:
{decision.brain_skipped_reason}

DECISION_SOURCE_PATH:
{decision.decision_source_path}

ESCALATION_REASON:
{decision.escalation_reason}

AUTO_FIX_AVAILABLE:
{"yes" if decision.auto_fix_available else "no"}
{patch_validation_block}

AUTO_FIX_PLAN:
{decision.auto_fix_plan}

AUTO_FIX_BLOCK_REASON:
{block_reason}

SAFETY_REASON:
{decision.safety_policy_reason}

MANUAL_REVIEW_REQUIRED:
{"yes" if decision.manual_review_required else "no"}

PATCH:

```python
{patch_text}
```

SAFETY:
* backup will be created
* no unrelated code changes
* no file deletion
"""
