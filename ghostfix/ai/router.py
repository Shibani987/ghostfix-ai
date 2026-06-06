"""
AIRouter
Selects and calls the correct AI provider based on config.
Builds the prompt and parses the JSON response.
"""
import json
import re

from ghostfix.core.error_parser import ParsedError
from ghostfix.core.context_builder import CodeContext


SYSTEM_PROMPT = """\
You are GhostFix, an expert debugging assistant embedded in a developer's terminal.

Analyze the error and code context provided. Respond ONLY with a valid JSON object — no markdown, no preamble, no explanation outside the JSON.

JSON schema:
{
  "root_cause": "<2-3 sentence clear explanation of WHY the error happened>",
  "explanation": "<deeper technical explanation>",
  "fix_suggestion": "<what the developer should do to fix it>",
  "patch": "<unified diff patch string, or empty string if no patch needed>",
  "confidence": <float 0.0-1.0>,
  "related_files": ["<other files that may need changes>"]
}

Patch format rules:
- Use standard unified diff format (--- a/file, +++ b/file, @@ hunks)
- Include enough context lines (3) around changes
- Only patch what is necessary
- If the fix requires running a command (e.g. migrations), set patch to "" and explain in fix_suggestion
"""


def _build_user_prompt(parsed: ParsedError, context: CodeContext) -> str:
    parts = [
        f"LANGUAGE: {parsed.language}",
        f"ERROR TYPE: {parsed.error_type}",
        f"ERROR MESSAGE: {parsed.error_message}",
        "",
        "=== FULL ERROR OUTPUT ===",
        parsed.raw[:3000],
        "",
    ]

    if context.primary_file and context.primary_snippet:
        parts += [
            f"=== PRIMARY FILE: {context.primary_file} ===",
            context.primary_snippet,
            "",
        ]

    for rf in context.related_files:
        parts += [
            f"=== RELATED FILE: {rf['path']} (around line {rf['line']}) ===",
            rf["snippet"],
            "",
        ]

    if context.project_tree:
        parts += [
            "=== PROJECT STRUCTURE ===",
            context.project_tree[:1500],
            "",
        ]

    return "\n".join(parts)


def _parse_response(text: str) -> dict | None:
    """Extract JSON from AI response, handle markdown fences."""
    text = text.strip()
    # Strip ```json ... ``` fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in response
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return None


class AIRouter:
    def __init__(self, config: dict):
        self.config = config
        self._provider = None
        self._init_provider()

    def _init_provider(self):
        model_cfg = self.config.get("model")
        if model_cfg and model_cfg.get("type") == "custom":
            from ghostfix.ai.custom_provider import CustomProvider
            self._provider = CustomProvider(model_cfg)
            return

        provider_name = self.config.get("provider", "openai")
        api_key = self.config.get("api_key", "")

        if provider_name == "openai":
            from ghostfix.ai.openai_provider import OpenAIProvider
            self._provider = OpenAIProvider(api_key)
        elif provider_name == "claude":
            from ghostfix.ai.claude_provider import ClaudeProvider
            self._provider = ClaudeProvider(api_key)
        elif provider_name == "gemini":
            from ghostfix.ai.gemini_provider import GeminiProvider
            self._provider = GeminiProvider(api_key)
        else:
            raise ValueError(f"Unknown provider: {provider_name}")

    def analyze(self, parsed: ParsedError, context: CodeContext) -> dict | None:
        user_msg = _build_user_prompt(parsed, context)
        raw = self._provider.complete(
            system=SYSTEM_PROMPT,
            user=user_msg,
        )
        if not raw:
            return None
        result = _parse_response(raw)
        return result
