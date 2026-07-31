from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.llm.config import LLMSettings
from app.llm.errors import LLMProviderError, flatten_error_detail, provider_error
from app.llm.json_utils import extract_json_object


class OpenAICompatibleProvider:
    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings

    def _api_base_url(self) -> str:
        parsed = urlsplit(self.settings.base_url)
        path = parsed.path.rstrip("/")
        if not path:
            path = "/v1"
        return urlunsplit((parsed.scheme, parsed.netloc, path + "/", "", ""))

    async def structured_chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        formats: list[dict[str, Any] | None] = [
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_response",
                    "strict": True,
                    "schema": response_schema,
                },
            },
            {"type": "json_object"},
            None,
        ]
        last_error: LLMProviderError | None = None
        for response_format in formats:
            try:
                return await self._request(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_format=response_format,
                )
            except _UnsupportedResponseFormat as exc:
                last_error = exc
        raise last_error or LLMProviderError("Structured response failed")

    async def unload(self) -> dict[str, Any]:
        return {
            "succeeded": True,
            "model": self.settings.model,
            "message": "Provider does not require explicit unload",
        }

    async def _request(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        headers = {"Accept": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        try:
            async with httpx.AsyncClient(
                base_url=self._api_base_url(),
                headers=headers,
                timeout=httpx.Timeout(
                    self.settings.timeout_seconds,
                    connect=self.settings.connect_timeout_seconds,
                ),
            ) as client:
                response = await client.post("chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMProviderError("LLM request timed out", infrastructure=True) from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(
                f"Cannot connect to LLM provider: {exc.__class__.__name__}",
                infrastructure=True,
            ) from exc
        if not response.is_success:
            try:
                detail = flatten_error_detail(response.json())
            except ValueError:
                detail = response.text
            if self.settings.api_key:
                detail = detail.replace(self.settings.api_key, "[redacted]")
            message = f"Upstream HTTP {response.status_code}: {detail[:500]}"
            if response.status_code in {400, 404, 415, 422} and response_format is not None:
                raise _UnsupportedResponseFormat(message)
            error = provider_error(message)
            if response.status_code >= 500:
                error.infrastructure = True
            raise error
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("Unexpected LLM provider response") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError("LLM provider response content is empty")
        return extract_json_object(content)


class _UnsupportedResponseFormat(LLMProviderError):
    pass
