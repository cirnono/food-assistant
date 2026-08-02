from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

import httpx
from fastapi import HTTPException


MEALIE_BASE_URL = os.environ.get(
    "MEALIE_BASE_URL",
    "http://host.docker.internal:9925",
).rstrip("/")

MEALIE_TOKEN_FILE = os.environ.get("MEALIE_TOKEN_FILE", "").strip()


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


MEALIE_TIMEOUT_SECONDS = _positive_float(
    "MEALIE_TIMEOUT_SECONDS",
    90.0,
)
MEALIE_CONNECT_TIMEOUT_SECONDS = _positive_float(
    "MEALIE_CONNECT_TIMEOUT_SECONDS",
    5.0,
)
MEALIE_WRITE_TIMEOUT_SECONDS = _positive_float(
    "MEALIE_WRITE_TIMEOUT_SECONDS",
    10.0,
)
MEALIE_POOL_TIMEOUT_SECONDS = _positive_float(
    "MEALIE_POOL_TIMEOUT_SECONDS",
    10.0,
)

_client: httpx.AsyncClient | None = None


def read_mealie_token() -> str:
    environment_token = os.environ.get("MEALIE_TOKEN", "").strip()
    if environment_token:
        return environment_token
    candidates = []
    if MEALIE_TOKEN_FILE:
        candidates.append(Path(MEALIE_TOKEN_FILE))
    candidates.extend(
        (Path("/run/secrets/mealie_token"), Path("/secrets/mealie_token"))
    )
    for path in candidates:
        try:
            token = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if token:
            return token
    raise RuntimeError("Mealie token is not configured or is empty")


async def start_mealie_client() -> None:
    """Create the process-wide Mealie client during application startup."""
    global _client
    if _client is not None:
        return
    _client = httpx.AsyncClient(
        base_url=MEALIE_BASE_URL,
        headers={
            "Authorization": f"Bearer {read_mealie_token()}",
            "Accept": "application/json",
        },
        timeout=httpx.Timeout(
            connect=MEALIE_CONNECT_TIMEOUT_SECONDS,
            read=MEALIE_TIMEOUT_SECONDS,
            write=MEALIE_WRITE_TIMEOUT_SECONDS,
            pool=MEALIE_POOL_TIMEOUT_SECONDS,
        ),
        limits=httpx.Limits(
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=30.0,
        ),
    )


async def close_mealie_client() -> None:
    """Close the shared connection pool during application shutdown."""
    global _client
    client, _client = _client, None
    if client is not None:
        await client.aclose()


def get_mealie_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("Mealie HTTP client is not initialized")
    return _client


async def mealie_get(
    path: str,
    params: Mapping[str, Any] | None = None,
) -> httpx.Response:
    try:
        return await get_mealie_client().get(
            path,
            params=params,
        )

    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="Mealie request timed out",
        ) from exc

    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Cannot connect to Mealie: "
                f"{exc.__class__.__name__}"
            ),
        ) from exc


def decode_response(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {
            "content_type": response.headers.get(
                "content-type"
            ),
            "body": response.text[:1000],
        }


def raise_for_mealie_error(
    response: httpx.Response,
    message: str,
) -> None:
    if response.is_success:
        return

    raise HTTPException(
        status_code=502,
        detail={
            "message": message,
            "upstream_http_status": response.status_code,
            "upstream_response": decode_response(response),
        },
    )
