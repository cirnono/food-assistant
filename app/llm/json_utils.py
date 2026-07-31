from __future__ import annotations

import json
import re
from typing import Any

from app.llm.errors import LLMProviderError


def extract_json_object(content: str) -> dict[str, Any]:
    cleaned = re.sub(
        r"<think>.*?</think>",
        "",
        content.strip(),
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    decoder = json.JSONDecoder()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        payload = None
        for index, character in enumerate(cleaned):
            if character != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(cleaned[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                payload = candidate
                break
        if payload is None:
            raise LLMProviderError("Model returned invalid JSON")
    if not isinstance(payload, dict):
        raise LLMProviderError("Model response must be a JSON object")
    return payload
