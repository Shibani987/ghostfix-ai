"""
CustomProvider
Calls any OpenAI-compatible endpoint (Ollama, LM Studio, vLLM,
your own server, etc.) defined in ghostfix.config.py.

Expected request format (OpenAI-compatible):
  POST /v1/chat/completions  OR  /api/chat (Ollama)
  { "model": "...", "messages": [...] }

Expected response (either format):
  OpenAI:  { "choices": [{ "message": { "content": "..." } }] }
  Ollama:  { "message": { "content": "..." } }
"""
import httpx
from ghostfix.ai.base import BaseProvider


class CustomProvider(BaseProvider):
    def __init__(self, model_cfg: dict):
        self.endpoint = model_cfg["endpoint"].rstrip("/")
        self.model_name = model_cfg.get("model_name", "")
        self.api_key = model_cfg.get("api_key", "")
        self.extra_headers = model_cfg.get("headers", {})
        self.timeout = model_cfg.get("timeout_seconds", 120)

        # Auto-detect Ollama vs OpenAI-compatible
        self._is_ollama = "ollama" in self.endpoint or "/api/chat" in self.endpoint

    def complete(self, system: str, user: str) -> str | None:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.extra_headers)

        if self._is_ollama:
            return self._call_ollama(headers, system, user)
        else:
            return self._call_openai_compat(headers, system, user)

    def _call_ollama(self, headers: dict, system: str, user: str) -> str | None:
        """Ollama /api/chat format."""
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0.2},
        }
        url = self.endpoint
        if not url.endswith("/api/chat"):
            url = url.rstrip("/") + "/api/chat"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                # Ollama returns { "message": { "content": "..." } }
                return data.get("message", {}).get("content")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Custom model error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            raise RuntimeError(f"Custom model request failed: {e}")

    def _call_openai_compat(self, headers: dict, system: str, user: str) -> str | None:
        """OpenAI-compatible /v1/chat/completions format."""
        payload = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": 2000,
        }
        if self.model_name:
            payload["model"] = self.model_name

        url = self.endpoint
        if not url.endswith("/chat/completions"):
            url = url.rstrip("/") + "/v1/chat/completions"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Custom model error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            raise RuntimeError(f"Custom model request failed: {e}")
