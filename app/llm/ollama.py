from __future__ import annotations

from typing import Any

import httpx

from app.llm.config import LLMSettings
from app.llm.errors import LLMProviderError, flatten_error_detail, provider_error
from app.llm.json_utils import extract_json_object


class OllamaProvider:
    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings

    async def structured_chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        del response_schema  # Ollama's json mode is retained for compatibility.
        payload = {
            "model": self.settings.model,
            "stream": False,
            "think": False,
            "keep_alive": self.settings.keep_alive,
            "format": "json",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": self.settings.temperature,
                "num_ctx": self.settings.context_length,
                "num_predict": self.settings.max_tokens,
            },
        }
        response = await self._post("/api/chat", payload)
        message = response.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError("Ollama response content is empty")
        return extract_json_object(content)

    async def tags(self) -> dict[str, Any]:
        try:
            async with self._client(timeout_seconds=15, connect_seconds=5) as client:
                response = await client.get("/api/tags")
        except httpx.TimeoutException as exc:
            raise LLMProviderError(
                "Ollama status request timed out", infrastructure=True
            ) from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(
                f"Cannot connect to Ollama: {exc.__class__.__name__}",
                infrastructure=True,
            ) from exc
        return self._decode_response(response, "Ollama tags")

    async def unload(self) -> dict[str, Any]:
        payload = {
            "model": self.settings.model,
            "prompt": "",
            "stream": False,
            "keep_alive": 0,
        }
        try:
            await self._post("/api/generate", payload, timeout_seconds=30)
        except LLMProviderError as exc:
            return {"succeeded": False, "error": str(exc)}
        return {"succeeded": True, "model": self.settings.model}

    def _client(
        self,
        *,
        timeout_seconds: float | None = None,
        connect_seconds: float | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.settings.base_url,
            timeout=httpx.Timeout(
                timeout_seconds or self.settings.timeout_seconds,
                connect=connect_seconds or self.settings.connect_timeout_seconds,
            ),
        )

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        try:
            async with self._client(timeout_seconds=timeout_seconds) as client:
                response = await client.post(path, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMProviderError(
                "Ollama generation timed out", infrastructure=True
            ) from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(
                f"Cannot connect to Ollama: {exc.__class__.__name__}",
                infrastructure=True,
            ) from exc
        return self._decode_response(response, "Ollama")

    @staticmethod
    def _decode_response(response: httpx.Response, label: str) -> dict[str, Any]:
        if not response.is_success:
            try:
                detail = flatten_error_detail(response.json())
            except ValueError:
                detail = response.text
            message = f"{label} returned HTTP {response.status_code}: {detail[:500]}"
            error = provider_error(message)
            if response.status_code >= 500:
                error.infrastructure = True
            raise error
        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMProviderError(f"Unexpected {label} response") from exc
        if not isinstance(payload, dict):
            raise LLMProviderError(f"Unexpected {label} response")
        return payload
