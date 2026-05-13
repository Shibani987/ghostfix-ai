from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.autofix import build_patch_plan
from core.decision_engine import decide_fix


@dataclass
class PatchProposal:
    root_cause: str
    fix: str
    confidence: int
    source: str
    auto_fix_available: bool
    patch_plan: str
    patch: str = ""
    safe_block: Optional[Dict[str, Any]] = None
    similar_fixes: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root_cause": self.root_cause,
            "fix": self.fix,
            "confidence": self.confidence,
            "source": self.source,
            "auto_fix_available": self.auto_fix_available,
            "patch_plan": self.patch_plan,
            "patch": self.patch,
            "safe_block": self.safe_block,
            "similar_fixes": self.similar_fixes,
        }


class PatchGenerator:
    """Use local model/retriever output for diagnosis, then expose only safe patches."""

    def generate(self, evidence) -> PatchProposal:
        model_result = self._ask_local_model(evidence)
        decision = self._decision_from_model_or_retriever(evidence, model_result)
        safe_plan = self._safe_patch_block(evidence, decision)

        confidence = int(model_result.get("confidence") or min(evidence.confidence, decision.confidence))

        root_cause = evidence.root_cause
        if root_cause.startswith("Low confidence") and confidence >= 65 and model_result.get("cause"):
            root_cause = model_result["cause"]

        retrieved_fix = model_result.get("fix") or ""
        if self._retrieved_fix_allowed(retrieved_fix, evidence, confidence):
            fix = retrieved_fix
            source = model_result.get("mode") or "retriever"
        else:
            fix = self._fallback_fix(evidence, decision, safe_plan)
            source = "analyzer/fallback"

        patch_plan = (safe_plan or {}).get("reason") or model_result.get("patch_plan") or decision.auto_fix_plan
        if evidence.error_type == "SyntaxError" and safe_plan and safe_plan.get("available"):
            patch_plan = safe_plan["reason"]

        return PatchProposal(
            root_cause=root_cause,
            fix=fix,
            confidence=max(0, min(100, confidence)),
            source=source,
            auto_fix_available=bool(safe_plan and safe_plan.get("available")),
            patch_plan=patch_plan,
            patch=(safe_plan or {}).get("patch", ""),
            safe_block=safe_plan,
            similar_fixes=model_result.get("retrieved_records") or [],
        )

    def _ask_local_model(self, evidence) -> Dict[str, Any]:
        try:
            from ml.model_inference import analyze_debug_case

            return analyze_debug_case(
                evidence.raw_traceback,
                evidence.code_context.get("snippet", ""),
                evidence.model_prompt,
            )
        except Exception:
            return {"mode": "retriever_unavailable"}

    def _decision_from_model_or_retriever(self, evidence, model_result: Dict[str, Any]):
        parsed = {
            "raw": evidence.raw_traceback,
            "type": evidence.error_type,
            "message": evidence.error_message,
            "file": evidence.file_path,
            "line": evidence.line_number,
            "missing_package": None,
        }
        return decide_fix(parsed, evidence.code_context, use_llm=False)

    def _safe_patch_block(self, evidence, decision) -> Optional[Dict[str, Any]]:
        if not evidence.file_path:
            return None
        parsed = {
            "raw": evidence.raw_traceback,
            "type": evidence.error_type,
            "message": evidence.error_message,
            "file": evidence.file_path,
            "line": evidence.line_number,
        }
        plan = build_patch_plan(evidence.file_path, parsed, decision.to_dict())
        if not plan.available:
            return {"available": False, "reason": plan.reason}
        return {
            "available": True,
            "reason": plan.reason,
            "file_path": evidence.file_path,
            "start_line": plan.start_line,
            "end_line": plan.end_line,
            "replacement": plan.replacement,
            "patch": plan.preview,
        }

    def _retrieved_fix_allowed(self, fix: str, evidence, confidence: int) -> bool:
        if not fix or confidence < 65:
            return False
        if evidence.error_type in {"NameError", "SyntaxError", "IndentationError"}:
            return False
        if self._is_url_only_fix(fix) or self._has_bad_fix_noise(fix):
            return False
        return self._fix_mentions_relevant_evidence(fix, evidence)

    def _fallback_fix(self, evidence, decision, safe_plan: Optional[Dict[str, Any]]) -> str:
        if evidence.error_type == "NameError":
            name = evidence.missing_name or self._extract_missing_name(evidence.error_message) or "the missing name"
            return f"Define `{name}` before use or check spelling."

        if evidence.error_type == "SyntaxError":
            if safe_plan and safe_plan.get("available") and "missing-colon" in safe_plan.get("reason", ""):
                return "Add the missing colon at the end of the failing statement."
            return "Fix the syntax at the traceback line before rerunning."

        if evidence.error_type == "ModuleNotFoundError":
            module = self._extract_missing_module(evidence.error_message)
            if module:
                return f"Install `{module}` in the active environment or fix the import/module name."

        return decision.fix or "Inspect the traceback and local code context before changing code."

    def _fix_mentions_relevant_evidence(self, fix: str, evidence) -> bool:
        low = fix.lower()
        if evidence.missing_name and evidence.missing_name.lower() in low:
            return True

        missing_module = self._extract_missing_module(evidence.error_message)
        if missing_module and missing_module.lower().split(".")[0] in low:
            return True

        missing_file = self._extract_missing_file(evidence.error_message)
        if missing_file and missing_file.lower().split("\\")[-1].split("/")[-1] in low:
            return True

        failing_tokens = self._important_tokens(evidence.failing_line)
        if failing_tokens and any(token in low for token in failing_tokens):
            return True

        return False

    def _is_url_only_fix(self, fix: str) -> bool:
        stripped = fix.strip()
        without_urls = re.sub(r"https?://\S+", "", stripped).strip()
        return bool(re.search(r"https?://\S+", stripped)) and len(without_urls.split()) <= 3

    def _has_bad_fix_noise(self, fix: str) -> bool:
        patterns = [
            r"Traceback \(most recent call last\):",
            r"\b(INFO|ERROR|DEBUG|WARNING|WARN)\b",
            r"\bmaybe\b",
            r"\bnot sure\b",
            r"\bhmm+\b",
            r"\bDocker image\b",
            r"\bCI failure\b",
            r"\breview fixes\b",
            r"\bpull request\b",
            r"\bIssue Planner\b",
            r"\bPlan ready\b",
            r"\bOpen in Cursor\b",
            r"\bLeave Feedback\b",
            r"\bAsk Dosu\b",
        ]
        return any(re.search(pattern, fix, re.IGNORECASE) for pattern in patterns)

    def _extract_missing_name(self, message: str) -> Optional[str]:
        match = re.search(r"name ['\"]([^'\"]+)['\"] is not defined", message or "")
        return match.group(1) if match else None

    def _extract_missing_module(self, message: str) -> Optional[str]:
        match = re.search(r"No module named ['\"]([^'\"]+)['\"]", message or "")
        return match.group(1) if match else None

    def _extract_missing_file(self, message: str) -> Optional[str]:
        match = re.search(r"No such file or directory: ['\"]([^'\"]+)['\"]", message or "")
        return match.group(1) if match else None

    def _important_tokens(self, text: str) -> List[str]:
        ignored = {"print", "return", "await", "self", "none", "true", "false", "with", "open"}
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text or "")
        return [token.lower() for token in tokens if token.lower() not in ignored]
