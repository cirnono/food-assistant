from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx


OLLAMA_BASE_URL = os.environ.get(
    "OLLAMA_BASE_URL",
    "http://host.docker.internal:11434",
).rstrip("/")

OLLAMA_MODEL = os.environ.get(
    "OLLAMA_MODEL",
    "qwen3:8b",
)

OLLAMA_TIMEOUT_SECONDS = float(
    os.environ.get(
        "OLLAMA_TIMEOUT_SECONDS",
        "180",
    )
)

OLLAMA_KEEP_ALIVE = os.environ.get(
    "OLLAMA_KEEP_ALIVE",
    "10m",
)

OLLAMA_NUM_CTX = int(
    os.environ.get(
        "OLLAMA_NUM_CTX",
        "8192",
    )
)


class OllamaClientError(RuntimeError):
    """Raised when the Ollama service cannot complete a request."""


def _upstream_error(
    response: httpx.Response,
) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]

    if isinstance(payload, dict):
        error = payload.get("error")

        if isinstance(error, str):
            return error

    return str(payload)[:500]


def _extract_json_object(
    content: str,
) -> dict[str, Any]:
    """
    Parse structured output with defensive fallbacks.

    JSON Schema output should already be valid JSON, but this also
    tolerates accidental Markdown fences and older model think tags.
    """
    cleaned = content.strip()

    cleaned = re.sub(
        r"<think>.*?</think>",
        "",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(
            r"^```(?:json)?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\s*```$",
            "",
            cleaned,
        ).strip()

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")

        if start < 0 or end <= start:
            raise OllamaClientError(
                "Model response does not contain a JSON object"
            )

        try:
            payload = json.loads(
                cleaned[start:end + 1]
            )
        except json.JSONDecodeError as exc:
            raise OllamaClientError(
                "Model returned invalid JSON"
            ) from exc

    if not isinstance(payload, dict):
        raise OllamaClientError(
            "Model response must be a JSON object"
        )

    return payload


async def ollama_tags() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(
            base_url=OLLAMA_BASE_URL,
            timeout=httpx.Timeout(
                15.0,
                connect=5.0,
            ),
        ) as client:
            response = await client.get("/api/tags")
    except httpx.TimeoutException as exc:
        raise OllamaClientError(
            "Ollama status request timed out"
        ) from exc
    except httpx.RequestError as exc:
        raise OllamaClientError(
            f"Cannot connect to Ollama: "
            f"{exc.__class__.__name__}"
        ) from exc

    if not response.is_success:
        raise OllamaClientError(
            "Ollama returned "
            f"HTTP {response.status_code}: "
            f"{_upstream_error(response)}"
        )

    payload = response.json()

    if not isinstance(payload, dict):
        raise OllamaClientError(
            "Unexpected Ollama tags response"
        )

    return payload


async def ollama_structured_chat(
    *,
    system_prompt: str,
    user_prompt: str,
    response_schema: dict[str, Any],
) -> dict[str, Any]:
    request_payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "think": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "format": "json",
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "options": {
            "temperature": 0,
            "num_ctx": OLLAMA_NUM_CTX,
            "num_predict": 4096,
        },
    }

    try:
        async with httpx.AsyncClient(
            base_url=OLLAMA_BASE_URL,
            timeout=httpx.Timeout(
                OLLAMA_TIMEOUT_SECONDS,
                connect=10.0,
            ),
        ) as client:
            response = await client.post(
                "/api/chat",
                json=request_payload,
            )
    except httpx.TimeoutException as exc:
        raise OllamaClientError(
            "Ollama generation timed out"
        ) from exc
    except httpx.RequestError as exc:
        raise OllamaClientError(
            f"Cannot connect to Ollama: "
            f"{exc.__class__.__name__}"
        ) from exc

    if not response.is_success:
        raise OllamaClientError(
            "Ollama returned "
            f"HTTP {response.status_code}: "
            f"{_upstream_error(response)}"
        )

    response_payload = response.json()

    if not isinstance(response_payload, dict):
        raise OllamaClientError(
            "Unexpected Ollama chat response"
        )

    message = response_payload.get("message")

    if not isinstance(message, dict):
        raise OllamaClientError(
            "Ollama response contains no message"
        )

    content = message.get("content")

    if not isinstance(content, str) or not content.strip():
        raise OllamaClientError(
            "Ollama response content is empty"
        )

    return _extract_json_object(content)
