from __future__ import annotations

from app.api_auth import api_token_middleware
from app.review_ui import router as review_ui_router
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.database import (
    check_database,
    init_database,
)
from app.inventory import router as inventory_router
from app.ingredient_aliases import router as ingredient_aliases_router
from app.cooking_history import router as cooking_history_router
from app.pantry_ui import router as pantry_ui_router
from app.home_assistant import router as home_assistant_router
from app.cooking_sessions import router as cooking_sessions_router
from app.cooking_ui import router as cooking_ui_router
from app.consumption import router as consumption_router
from app.consumption_ui import router as consumption_ui_router
from app.shopping import router as shopping_router
from app.shopping_ui import router as shopping_ui_router
from app.data_quality import router as data_quality_router
from app.quality_ui import router as quality_ui_router
from app.github_sources import router as github_sources_router
from app.import_queue import router as import_queue_router
from app.ai_recipes import router as ai_recipes_router
from app.mealie_client import (
    MEALIE_BASE_URL,
    close_mealie_client,
    decode_response,
    mealie_get,
    start_mealie_client,
)
from app.recommendations import (
    router as recommendations_router,
)
from app.system_api import router as system_router


APP_VERSION = "0.25.1"


@asynccontextmanager
async def lifespan(application: FastAPI):
    del application

    init_database()
    await start_mealie_client()
    try:
        yield
    finally:
        await close_mealie_client()


app = FastAPI(
    title="Food Assistant",
    description=(
        "Local cooking, pantry and meal "
        "recommendation service."
    ),
    version=APP_VERSION,
    lifespan=lifespan,
)

app.include_router(inventory_router)
app.include_router(recommendations_router)
app.include_router(ingredient_aliases_router)
app.include_router(cooking_history_router)
app.include_router(pantry_ui_router)
app.include_router(home_assistant_router)
app.include_router(cooking_sessions_router)
app.include_router(cooking_ui_router)
app.include_router(consumption_router)
app.include_router(consumption_ui_router)
app.include_router(shopping_router)
app.include_router(shopping_ui_router)
app.include_router(data_quality_router)
app.include_router(quality_ui_router)
app.include_router(ai_recipes_router)
app.include_router(github_sources_router)
app.include_router(import_queue_router)
app.include_router(system_router)


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "service": "food-assistant",
        "version": APP_VERSION,
        "status": "running",
        "documentation": "/docs",
        "endpoints": {
            "health": "/healthz",
            "readiness": "/readyz",
            "inventory": "/api/v1/inventory",
            "inventory_summary": (
                "/api/v1/inventory/summary"
            ),
            "recommendation_preview": (
                "/api/v1/recommendations/preview"
            ),
            "recommendations": "/api/v1/recommendations",
            "pantry_ui": "/pantry",
            "recommendations_ui": "/recommendations",
            "cooking_ui": "/cook",
            "consumption_ui": "/consumption",
            "shopping_ui": "/shopping",
            "quality_ui": "/quality",
            "active_cooking": "/api/v1/cooking-sessions/active-state",
            "home_assistant_state": "/api/v1/home-assistant/state",
            "mealie_status": (
                "/api/v1/integrations/mealie/status"
            ),
            "today_mealplan": (
                "/api/v1/mealie/mealplans/today"
            ),
        },
    }


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "food-assistant",
        "version": APP_VERSION,
    }


@app.get("/readyz")
def readyz() -> dict[str, str]:
    try:
        check_database()
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from exc

    return {
        "status": "ready",
        "database": "ok",
    }


@app.get("/api/v1/integrations/mealie/status")
async def mealie_status() -> dict[str, Any]:
    try:
        response = await mealie_get(
            "/api/households/mealplans/today"
        )
    except HTTPException as exc:
        return {
            "status": "unavailable",
            "mealie_base_url": MEALIE_BASE_URL,
            "detail": exc.detail,
        }

    return {
        "status": (
            "ok" if response.is_success else "error"
        ),
        "mealie_base_url": MEALIE_BASE_URL,
        "upstream_http_status": response.status_code,
        "token_configured": True,
    }


@app.get("/api/v1/mealie/mealplans/today")
async def today_mealplan() -> Any:
    response = await mealie_get(
        "/api/households/mealplans/today"
    )

    if not response.is_success:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Mealie returned an error",
                "upstream_http_status": (
                    response.status_code
                ),
                "upstream_response": (
                    decode_response(response)
                ),
            },
        )

    return decode_response(response)

app.include_router(review_ui_router)

app.middleware("http")(api_token_middleware)
