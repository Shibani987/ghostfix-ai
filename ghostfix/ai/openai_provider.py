import httpx
from ghostfix.ai.base import BaseProvider

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(BaseProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def complete(self, system: str, user: str) -> str | None:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": 2000,
        }
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(OPENAI_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"OpenAI API error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            raise RuntimeError(f"OpenAI request failed: {e}")
