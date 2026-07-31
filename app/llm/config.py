from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from app.llm.errors import LLMConfigurationError


logger = logging.getLogger(__name__)
_legacy_warning_emitted = False


def _new_or_legacy(
    new_name: str,
    legacy_name: str | None,
    default: str,
) -> tuple[str, bool]:
    if new_name in os.environ:
        return os.environ[new_name], False
    if legacy_name and legacy_name in os.environ:
        return os.environ[legacy_name], True
    return default, False


def _parse_bool(name: str, value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise LLMConfigurationError(f"{name} must be a boolean")


def _read_api_key() -> str:
    key_file = os.environ.get("LLM_API_KEY_FILE", "").strip()
    if key_file:
        try:
            return Path(key_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise LLMConfigurationError(
                "Cannot read configured LLM API key file"
            ) from exc
    return os.environ.get("LLM_API_KEY", "").strip()


@dataclass(frozen=True, slots=True)
class LLMSettings:
    provider: str
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float
    connect_timeout_seconds: float
    max_tokens: int
    temperature: float
    context_length: int
    keep_alive: str
    unload_after_batch: bool
    legacy_config_in_use: bool

    @classmethod
    def from_env(cls) -> "LLMSettings":
        provider, provider_legacy = _new_or_legacy(
            "LLM_PROVIDER", None, "ollama"
        )
        base_url, base_legacy = _new_or_legacy(
            "LLM_BASE_URL",
            "OLLAMA_BASE_URL",
            "http://host.docker.internal:11434",
        )
        model, model_legacy = _new_or_legacy(
            "LLM_MODEL", "OLLAMA_MODEL", "qwen3:8b"
        )
        timeout, timeout_legacy = _new_or_legacy(
            "LLM_TIMEOUT_SECONDS", "OLLAMA_TIMEOUT_SECONDS", "300"
        )
        context, context_legacy = _new_or_legacy(
            "LLM_CONTEXT_LENGTH", "OLLAMA_NUM_CTX", "6144"
        )
        keep_alive, keep_alive_legacy = _new_or_legacy(
            "LLM_KEEP_ALIVE", "OLLAMA_KEEP_ALIVE", "10m"
        )
        legacy = any(
            (
                provider_legacy,
                base_legacy,
                model_legacy,
                timeout_legacy,
                context_legacy,
                keep_alive_legacy,
            )
        )
        global _legacy_warning_emitted
        if legacy and not _legacy_warning_emitted:
            logger.warning(
                "OLLAMA_* configuration is deprecated; use LLM_* variables"
            )
            _legacy_warning_emitted = True

        normalized_provider = provider.strip().casefold().replace("-", "_")
        if normalized_provider not in {"ollama", "openai_compatible"}:
            raise LLMConfigurationError("Unsupported LLM provider")
        try:
            settings = cls(
                provider=normalized_provider,
                base_url=base_url.strip().rstrip("/"),
                api_key=_read_api_key(),
                model=model.strip(),
                timeout_seconds=float(timeout),
                connect_timeout_seconds=float(
                    os.environ.get("LLM_CONNECT_TIMEOUT_SECONDS", "10")
                ),
                max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "4096")),
                temperature=float(os.environ.get("LLM_TEMPERATURE", "0")),
                context_length=int(context),
                keep_alive=keep_alive.strip(),
                unload_after_batch=_parse_bool(
                    "LLM_UNLOAD_AFTER_BATCH",
                    os.environ.get("LLM_UNLOAD_AFTER_BATCH", "true"),
                ),
                legacy_config_in_use=legacy,
            )
        except ValueError as exc:
            raise LLMConfigurationError(
                "Invalid numeric LLM configuration"
            ) from exc
        if not settings.base_url or not settings.model:
            raise LLMConfigurationError("LLM base URL and model are required")
        if settings.timeout_seconds <= 0 or settings.connect_timeout_seconds <= 0:
            raise LLMConfigurationError("LLM timeouts must be positive")
        if settings.max_tokens <= 0 or settings.context_length <= 0:
            raise LLMConfigurationError("LLM token limits must be positive")
        return settings
