import httpx
from ghostfix.ai.base import BaseProvider


class GeminiProvider(BaseProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-1.5-pro:generateContent?key={api_key}"
        )

    def complete(self, system: str, user: str) -> str | None:
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [
                {"role": "user", "parts": [{"text": user}]}
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 2000,
            },
        }
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(self.url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Gemini API error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            raise RuntimeError(f"Gemini request failed: {e}")
