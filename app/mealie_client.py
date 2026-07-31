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

MEALIE_TOKEN_FILE = Path(
    os.environ.get(
        "MEALIE_TOKEN_FILE",
        "/run/secrets/mealie_token",
    )
)


def read_mealie_token() -> str:
    try:
        token = MEALIE_TOKEN_FILE.read_text(
            encoding="utf-8",
        ).strip()
    except OSError as exc:
        raise RuntimeError(
            f"Cannot read Mealie token file: "
            f"{MEALIE_TOKEN_FILE}"
        ) from exc

    if not token:
        raise RuntimeError("Mealie token file is empty")

    return token


async def mealie_get(
    path: str,
    params: Mapping[str, Any] | None = None,
) -> httpx.Response:
    token = read_mealie_token()

    try:
        async with httpx.AsyncClient(
            base_url=MEALIE_BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(20.0),
        ) as client:
            return await client.get(
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
