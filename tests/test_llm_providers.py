from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from app.llm.config import LLMSettings
from app.llm.errors import LLMProviderError, is_infrastructure_error
from app.llm.ollama import OllamaProvider
from app.llm.openai_compatible import OpenAICompatibleProvider


def settings(**changes: object) -> LLMSettings:
    base = LLMSettings(
        provider="ollama",
        base_url="http://llm.example.test:11434",
        api_key="",
        model="example-model",
        timeout_seconds=30,
        connect_timeout_seconds=2,
        max_tokens=256,
        temperature=0,
        context_length=6144,
        keep_alive="10m",
        unload_after_batch=True,
        legacy_config_in_use=False,
    )
    return replace(base, **changes)


def mock_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def factory(**kwargs):
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_ollama_structured_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        assert b'"num_ctx":6144' in request.content
        return httpx.Response(
            200, json={"message": {"content": '{"name":"ok"}'}}
        )

    mock_client(monkeypatch, handler)
    result = await OllamaProvider(settings()).structured_chat(
        system_prompt="system", user_prompt="user", response_schema={}
    )
    assert result == {"name": "ok"}


@pytest.mark.asyncio
async def test_openai_json_schema_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert b'"json_schema"' in request.content
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok":true}'}}]}
        )

    mock_client(monkeypatch, handler)
    provider = OpenAICompatibleProvider(
        settings(provider="openai_compatible", base_url="https://api.example.test")
    )
    assert await provider.structured_chat(
        system_prompt="system",
        user_prompt="user",
        response_schema={"type": "object"},
    ) == {"ok": True}


@pytest.mark.asyncio
async def test_openai_falls_back_to_json_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.content)
        if len(requests) == 1:
            return httpx.Response(400, json={"error": "unsupported format"})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok":true}'}}]}
        )

    mock_client(monkeypatch, handler)
    provider = OpenAICompatibleProvider(settings(provider="openai_compatible"))
    assert await provider.structured_chat(
        system_prompt="system", user_prompt="user", response_schema={}
    ) == {"ok": True}
    assert b'"json_object"' in requests[1]


@pytest.mark.asyncio
async def test_openai_extracts_json_from_plain_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(422, json={"error": "format unsupported"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": 'Result follows: {"ok":true} done'}}
                ]
            },
        )

    mock_client(monkeypatch, handler)
    provider = OpenAICompatibleProvider(settings(provider="openai_compatible"))
    assert await provider.structured_chat(
        system_prompt="system", user_prompt="user", response_schema={}
    ) == {"ok": True}


@pytest.mark.asyncio
async def test_api_key_is_redacted_from_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = "example-sensitive-key-value"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {api_key}"
        return httpx.Response(401, json={"error": f"invalid {api_key}"})

    mock_client(monkeypatch, handler)
    provider = OpenAICompatibleProvider(
        settings(provider="openai_compatible", api_key=api_key)
    )
    with pytest.raises(LLMProviderError) as captured:
        await provider.structured_chat(
            system_prompt="system", user_prompt="user", response_schema={}
        )
    assert api_key not in str(captured.value)


def test_api_key_file_takes_priority(monkeypatch, tmp_path) -> None:
    key_file = tmp_path / "key"
    key_file.write_text(" file-key-value \n", encoding="utf-8")
    monkeypatch.setenv("LLM_API_KEY", "environment-key-value")
    monkeypatch.setenv("LLM_API_KEY_FILE", str(key_file))
    assert LLMSettings.from_env().api_key == "file-key-value"


def test_legacy_ollama_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(__import__("os").environ):
        if name.startswith("LLM_") or name.startswith("OLLAMA_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "legacy-model")
    monkeypatch.setenv("OLLAMA_NUM_CTX", "6000")
    resolved = LLMSettings.from_env()
    assert resolved.model == "legacy-model"
    assert resolved.context_length == 6000
    assert resolved.legacy_config_in_use is True


@pytest.mark.parametrize(
    "value",
    ["CUDA out of memory", "RemoteProtocolError: peer disconnected"],
)
def test_infrastructure_error_classification(value: str) -> None:
    assert is_infrastructure_error(value)


@pytest.mark.asyncio
async def test_provider_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow upstream", request=request)

    mock_client(monkeypatch, handler)
    provider = OpenAICompatibleProvider(settings(provider="openai_compatible"))
    with pytest.raises(LLMProviderError) as captured:
        await provider.structured_chat(
            system_prompt="system", user_prompt="user", response_schema={}
        )
    assert captured.value.infrastructure is True
