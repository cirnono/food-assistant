from __future__ import annotations

from app.llm.base import StructuredChatProvider
from app.llm.config import LLMSettings
from app.llm.ollama import OllamaProvider
from app.llm.openai_compatible import OpenAICompatibleProvider


def create_llm_provider(settings: LLMSettings | None = None) -> StructuredChatProvider:
    resolved = settings or LLMSettings.from_env()
    if resolved.provider == "ollama":
        return OllamaProvider(resolved)
    return OpenAICompatibleProvider(resolved)


def get_llm_provider() -> StructuredChatProvider:
    """Resolve configuration per call so runtime environment changes stay visible."""
    return create_llm_provider()
