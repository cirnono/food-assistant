"""Backward-compatible Ollama API backed by the provider abstraction."""
from __future__ import annotations

from typing import Any

from app.llm.config import LLMSettings
from app.llm.errors import LLMProviderError
from app.llm.factory import get_llm_provider
from app.llm.json_utils import extract_json_object
from app.llm.ollama import OllamaProvider

_settings = LLMSettings.from_env()
OLLAMA_BASE_URL = _settings.base_url
OLLAMA_MODEL = _settings.model
OLLAMA_TIMEOUT_SECONDS = _settings.timeout_seconds
OLLAMA_KEEP_ALIVE = _settings.keep_alive
OLLAMA_NUM_CTX = _settings.context_length

OllamaClientError = LLMProviderError


def _extract_json_object(content: str) -> dict[str, Any]:
    return extract_json_object(content)


async def ollama_structured_chat(
    *,
    system_prompt: str,
    user_prompt: str,
    response_schema: dict[str, Any],
) -> dict[str, Any]:
    return await get_llm_provider().structured_chat(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_schema=response_schema,
    )


async def ollama_tags() -> dict[str, Any]:
    provider = get_llm_provider()
    if not isinstance(provider, OllamaProvider):
        raise LLMProviderError(
            "Ollama status is unavailable for the configured provider"
        )
    return await provider.tags()
