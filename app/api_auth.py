from __future__ import annotations

import hmac
import os
from functools import lru_cache
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import Response


TOKEN_FILE_CANDIDATES = (
    "/run/secrets/food_assistant_api_token",
    "/secrets/food_assistant_api_token",
    "/srv/appdata/food-assistant/secrets/"
    "food_assistant_api_token",
)


class ApiTokenConfigurationError(
    RuntimeError
):
    pass


@lru_cache(maxsize=1)
def read_api_token() -> str:
    environment_token = os.getenv(
        "FOOD_ASSISTANT_API_TOKEN",
        "",
    ).strip()

    if environment_token:
        return environment_token

    configured_path = os.getenv(
        "FOOD_ASSISTANT_API_TOKEN_FILE",
        "",
    ).strip()

    paths: list[Path] = []

    if configured_path:
        paths.append(
            Path(configured_path)
        )

    paths.extend(
        Path(value)
        for value
        in TOKEN_FILE_CANDIDATES
    )

    checked: list[str] = []

    for path in paths:
        checked.append(str(path))

        if not path.is_file():
            continue

        token = path.read_text(
            encoding="utf-8"
        ).strip()

        if len(token) < 32:
            raise ApiTokenConfigurationError(
                "Food Assistant API token "
                "is too short"
            )

        return token

    raise ApiTokenConfigurationError(
        "Food Assistant API token was "
        "not found. Checked: "
        + ", ".join(checked)
    )


def supplied_token(
    request: Request,
) -> str:
    authorization = request.headers.get(
        "authorization",
        "",
    ).strip()

    prefix = "bearer "

    if authorization.casefold().startswith(
        prefix
    ):
        return authorization[
            len(prefix):
        ].strip()

    return request.headers.get(
        "x-food-assistant-token",
        "",
    ).strip()


async def api_token_middleware(
    request: Request,
    call_next,
) -> Response:
    path = request.url.path

    # 只保护业务 API。健康检查、文档和审核页面
    # 保持可访问，但页面没有令牌时读不到任何业务数据。
    if not path.startswith("/api/v1/"):
        return await call_next(request)

    if request.method == "OPTIONS":
        return await call_next(request)

    try:
        expected = read_api_token()

    except ApiTokenConfigurationError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "message": (
                        "Food Assistant API "
                        "authentication is not "
                        "configured"
                    ),
                    "error": str(exc),
                }
            },
        )

    received = supplied_token(request)

    if (
        not received
        or not hmac.compare_digest(
            received,
            expected,
        )
    ):
        return JSONResponse(
            status_code=401,
            headers={
                "WWW-Authenticate": "Bearer",
            },
            content={
                "detail": (
                    "Missing or invalid "
                    "Food Assistant API token"
                )
            },
        )

    return await call_next(request)
