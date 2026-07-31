from __future__ import annotations

from time import perf_counter
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException

from app.llm.config import LLMSettings
from app.llm.errors import LLMProviderError, sanitize_error
from app.llm.factory import create_llm_provider


router = APIRouter(prefix="/api/v1/system", tags=["system"])


def public_base_url(value: str) -> str:
    """Return only scheme, host and port, excluding credentials and paths."""
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        port = ""
    return urlunsplit((parsed.scheme, host + port, "", "", ""))


def provider_capabilities(provider: str) -> dict[str, bool]:
    return {
        "structured_chat": True,
        "json_schema": provider == "openai_compatible",
        "json_object_fallback": provider == "openai_compatible",
        "text_json_extraction": True,
        "explicit_model_unload": provider == "ollama",
    }


def llm_status_payload(settings: LLMSettings) -> dict[str, Any]:
    return {
        "provider": settings.provider,
        "base_url": public_base_url(settings.base_url),
        "model": settings.model,
        "configured": bool(settings.base_url and settings.model),
        "api_key_configured": bool(settings.api_key),
        "context_length": settings.context_length,
        "max_tokens": settings.max_tokens,
        "timeout_seconds": settings.timeout_seconds,
        "legacy_config_in_use": settings.legacy_config_in_use,
        "provider_capabilities": provider_capabilities(settings.provider),
    }


@router.get("/llm-status")
async def llm_status() -> dict[str, Any]:
    return llm_status_payload(LLMSettings.from_env())


@router.post("/llm-test")
async def llm_test() -> dict[str, Any]:
    settings = LLMSettings.from_env()
    provider = create_llm_provider(settings)
    started = perf_counter()
    latency_ms = 0.0
    try:
        result = await provider.structured_chat(
            system_prompt="Return only a JSON object matching the supplied schema.",
            user_prompt='Return {"ok": true}.',
            response_schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
        )
        if result.get("ok") is not True:
            raise LLMProviderError("LLM test returned an unexpected result")
        latency_ms = round((perf_counter() - started) * 1000, 1)
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "LLM connection test failed",
                "error": sanitize_error(exc),
            },
        ) from exc
    finally:
        if settings.unload_after_batch:
            try:
                await provider.unload()
            except Exception:
                pass
    return {
        "success": True,
        "latency_ms": latency_ms,
        "provider": settings.provider,
        "model": settings.model,
    }
