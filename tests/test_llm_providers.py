from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from app.ai_recipes import NormalizedRecipe
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
    schema = NormalizedRecipe.model_json_schema()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        payload = __import__("json").loads(request.content)
        assert payload["format"] == schema
        assert payload["format"] != "json"
        assert payload["format"]["properties"]["ingredients"]["minItems"] == 1
        assert payload["format"]["properties"]["instructions"]["minItems"] == 1
        assert payload["stream"] is False
        assert payload["think"] is False
        assert payload["options"] == {
            "temperature": 0,
            "num_ctx": 6144,
            "num_predict": 256,
        }
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": "result: " + __import__("json").dumps(
                        valid_recipe_payload()
                    )
                }
            },
        )

    mock_client(monkeypatch, handler)
    result = await OllamaProvider(settings()).structured_chat(
        system_prompt="system", user_prompt="user", response_schema=schema
    )
    assert NormalizedRecipe.model_validate(result).name == "ok"


@pytest.mark.asyncio
async def test_ollama_falls_back_once_for_grammar_http_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict] = []
    schema = NormalizedRecipe.model_json_schema()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(
                400,
                json={"error": "xgrammar: failed to parse JSON Schema grammar"},
            )
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": f"result: {json.dumps(valid_recipe_payload())}"
                }
            },
        )

    mock_client(monkeypatch, handler)
    result = await OllamaProvider(settings()).structured_chat(
        system_prompt="system", user_prompt="user", response_schema=schema
    )

    assert NormalizedRecipe.model_validate(result).name == "ok"
    assert len(requests) == 2
    assert requests[0]["format"] == schema
    assert requests[1]["format"] == "json"
    for key in ("model", "messages", "options", "think", "keep_alive", "stream"):
        assert requests[1][key] == requests[0][key]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "detail"),
    [
        (400, "invalid value for num_ctx"),
        (400, "model not found while initializing grammar"),
        (400, "CUDA out of memory during grammar initialization"),
        (401, "failed to parse JSON schema grammar"),
        (403, "failed to parse JSON schema grammar"),
        (404, "model not found: failed to initialize grammar"),
        (500, "grammar initialization failed"),
    ],
)
async def test_ollama_does_not_fallback_for_other_http_errors(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    detail: str,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code, json={"error": detail})

    mock_client(monkeypatch, handler)
    with pytest.raises(LLMProviderError):
        await OllamaProvider(settings()).structured_chat(
            system_prompt="system",
            user_prompt="user",
            response_schema={"type": "object"},
        )
    assert attempts == 1


@pytest.mark.asyncio
async def test_ollama_does_not_fallback_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("grammar initialization timed out", request=request)

    mock_client(monkeypatch, handler)
    with pytest.raises(LLMProviderError) as captured:
        await OllamaProvider(settings()).structured_chat(
            system_prompt="system",
            user_prompt="user",
            response_schema={"type": "object"},
        )
    assert captured.value.infrastructure is True
    assert attempts == 1


@pytest.mark.asyncio
async def test_ollama_fallback_failure_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            400,
            json={"error": "grammar initialization failed"},
        )

    mock_client(monkeypatch, handler)
    with pytest.raises(LLMProviderError):
        await OllamaProvider(settings()).structured_chat(
            system_prompt="system",
            user_prompt="user",
            response_schema={"type": "object"},
        )
    assert attempts == 2


@pytest.mark.asyncio
async def test_ollama_fallback_warning_does_not_log_sensitive_input(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    prompt_secret = "sensitive-prompt-value"
    schema_secret = "sensitive-schema-value"
    token_secret = "sensitive-token-value"
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(400, json={"error": "unable to parse schema grammar"})
        return httpx.Response(200, json={"message": {"content": '{"ok": true}'}})

    mock_client(monkeypatch, handler)
    result = await OllamaProvider(settings(api_key=token_secret)).structured_chat(
        system_prompt=prompt_secret,
        user_prompt=prompt_secret,
        response_schema={"description": schema_secret},
    )
    assert result == {"ok": True}
    assert (
        "Ollama rejected the supplied JSON Schema; falling back to JSON mode."
        in caplog.text
    )
    for secret in (prompt_secret, schema_secret, token_secret):
        assert secret not in caplog.text


@pytest.mark.asyncio
async def test_ollama_json_mode_result_still_requires_caller_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = valid_recipe_payload()
    invalid["ingredients"] = []
    invalid["instructions"] = []
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(400, json={"error": "failed to parse schema grammar"})
        return httpx.Response(
            200,
            json={"message": {"content": f"prefix {json.dumps(invalid)} suffix"}},
        )

    mock_client(monkeypatch, handler)
    result = await OllamaProvider(settings()).structured_chat(
        system_prompt="system",
        user_prompt="user",
        response_schema=NormalizedRecipe.model_json_schema(),
    )
    assert result["ingredients"] == []
    with pytest.raises(ValueError):
        NormalizedRecipe.model_validate(result)


def valid_recipe_payload() -> dict:
    return {
        "name": "ok",
        "original_name": "ok",
        "description": None,
        "cuisine": "中餐",
        "categories": ["晚餐"],
        "tags": [],
        "servings": None,
        "prep_time_minutes": None,
        "cook_time_minutes": None,
        "total_time_minutes": None,
        "ingredients": [
            {
                "food_name": "水",
                "quantity": None,
                "unit": None,
                "note": None,
                "original_text": "水",
            }
        ],
        "instructions": [{"step_number": 1, "text": "加水", "timers": []}],
        "source": {
            "source_name": None,
            "source_url": None,
            "source_path": None,
            "source_license": None,
        },
        "import_score": 80,
        "recommendation": "review",
        "possible_duplicate": False,
        "duplicate_candidates": [],
        "warnings": [],
        "review_required": True,
    }


@pytest.mark.asyncio
async def test_ollama_does_not_send_or_log_api_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "do-not-log-this-api-key"

    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(500, json={"error": "upstream failed"})

    mock_client(monkeypatch, handler)
    provider = OllamaProvider(settings(api_key=secret))
    with pytest.raises(LLMProviderError):
        await provider.structured_chat(
            system_prompt="system",
            user_prompt="user",
            response_schema={"type": "object"},
        )
    assert secret not in caplog.text


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
