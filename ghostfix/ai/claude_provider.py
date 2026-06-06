import httpx
from ghostfix.ai.base import BaseProvider

CLAUDE_URL = "https://api.anthropic.com/v1/messages"


class ClaudeProvider(BaseProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def complete(self, system: str, user: str) -> str | None:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "claude-opus-4-6",
            "max_tokens": 2000,
            "system": system,
            "messages": [
                {"role": "user", "content": user},
            ],
        }
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(CLAUDE_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return data["content"][0]["text"]
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Claude API error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            raise RuntimeError(f"Claude request failed: {e}")
