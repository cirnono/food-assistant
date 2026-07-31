from __future__ import annotations

import re
from typing import Any


INFRASTRUCTURE_ERROR_MARKERS = (
    "cudamalloc failed",
    "cuda out of memory",
    "cuda error",
    "out of memory",
    "unable to allocate cuda",
    "llama-server process has terminated",
    "error loading model",
    "cannot connect",
    "connecterror",
    "failed to connect",
    "couldn't connect",
    "connection refused",
    "connect timeout",
    "connection timeout",
    "no route to host",
    "remoteprotocolerror",
    "server disconnected",
    "peer closed connection",
    "timed out",
    "timeout",
    "upstream http 5",
    "ollama returned http 5",
)


class LLMProviderError(RuntimeError):
    def __init__(self, message: str, *, infrastructure: bool = False) -> None:
        super().__init__(sanitize_error(message))
        self.infrastructure = infrastructure


def provider_error(message: str) -> LLMProviderError:
    """Build a sanitized error while retaining outage semantics."""
    return LLMProviderError(
        message,
        infrastructure=is_infrastructure_error(message),
    )


class LLMConfigurationError(LLMProviderError):
    pass


def sanitize_error(value: object) -> str:
    text = str(value)
    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+",
        r"\1[redacted]",
        text,
    )
    text = re.sub(
        r"(?i)((?:api[_-]?key|token|password|secret)\s*[:=]\s*)[^\s,;]+",
        r"\1[redacted]",
        text,
    )
    return text[:1000]


def flatten_error_detail(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(flatten_error_detail(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(flatten_error_detail(item) for item in value)
    return str(value)


def is_infrastructure_error(value: object) -> bool:
    if isinstance(value, LLMProviderError) and value.infrastructure:
        return True
    text = flatten_error_detail(value).casefold()
    return any(marker in text for marker in INFRASTRUCTURE_ERROR_MARKERS)
