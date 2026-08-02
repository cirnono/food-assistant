from __future__ import annotations

import asyncio
import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.mealie_client as mealie_client
import app.recommendations as recommendations
from app.database import Base


def response(payload=None, *, status=200, content=None, path="/api/recipes"):
    request = httpx.Request("GET", f"http://mealie{path}")
    if content is not None:
        return httpx.Response(status, content=content, request=request)
    return httpx.Response(status, json=payload, request=request)


@pytest.fixture(autouse=True)
def empty_cache():
    recommendations._recipe_cache.clear()
    recommendations._recipe_inflight.clear()
    yield
    recommendations._recipe_cache.clear()
    recommendations._recipe_inflight.clear()


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/recommendations.db")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def build(db: Session, **overrides):
    values = {
        "limit": 10,
        "max_missing": 10,
        "max_total_time": None,
        "category": None,
        "cuisine": None,
        "owner": None,
        "use_expiring": True,
        "randomize": False,
        "seed": None,
        "refresh_cache": False,
    }
    values.update(overrides)
    return recommendations.build_recommendations(db, **values)


@pytest.mark.asyncio
async def test_shared_mealie_client_lifecycle_and_timeout(monkeypatch):
    created = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False
            created.append(self)

        async def get(self, path, params=None):
            return response([], path=path)

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(mealie_client.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(mealie_client, "_client", None)
    monkeypatch.setattr(mealie_client, "read_mealie_token", lambda: "test-token")
    await mealie_client.start_mealie_client()
    await mealie_client.mealie_get("/one")
    await mealie_client.mealie_get("/two")
    assert len(created) == 1
    timeout = created[0].kwargs["timeout"]
    assert timeout.connect == mealie_client.MEALIE_CONNECT_TIMEOUT_SECONDS
    assert timeout.read == mealie_client.MEALIE_TIMEOUT_SECONDS
    assert created[0].kwargs["limits"].max_connections == 20
    await mealie_client.close_mealie_client()
    assert created[0].closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_type", "status"),
    [
        (httpx.ReadTimeout("slow"), "Timeout", None),
        (response({}, status=404), "UpstreamHTTPError", 404),
        (response(content=b"not-json"), "InvalidJSON", 200),
    ],
)
async def test_one_detail_failure_does_not_stop_others(monkeypatch, db, failure, expected_type, status):
    async def fake_get(path, params=None):
        if path == "/api/recipes":
            return response({"items": [{"slug": "bad"}, {"slug": "good"}], "total": 2})
        if path.endswith("bad"):
            if isinstance(failure, Exception):
                raise failure
            return failure
        return response({"name": "Good", "recipeIngredient": []}, path=path)

    monkeypatch.setattr(recommendations, "mealie_get", fake_get)
    result = await build(db)
    assert result["recipes_evaluated"] == 1
    assert len(result["recipe_detail_errors"]) == 1
    error = result["recipe_detail_errors"][0]["error"]
    assert "slug=bad" in error and f"type={expected_type}" in error
    if status is not None:
        assert f"upstream_status={status}" in error


@pytest.mark.asyncio
async def test_all_detail_failures_return_empty_groups(monkeypatch, db):
    async def fake_get(path, params=None):
        if path == "/api/recipes":
            return response({"items": [{"slug": "a"}, {"slug": "b"}], "total": 2})
        raise HTTPException(status_code=504, detail="timeout")

    monkeypatch.setattr(recommendations, "mealie_get", fake_get)
    result = await build(db)
    assert result["recipes_evaluated"] == 0
    assert len(result["recipe_detail_errors"]) == 2
    assert all(not result[key] for key in ("ready_now", "missing_one_or_two", "use_soon", "random_pick"))


@pytest.mark.asyncio
async def test_cache_hit_ttl_refresh_and_negative_cache(monkeypatch, db):
    calls = 0
    fail = False

    async def fake_get(path, params=None):
        nonlocal calls
        if path == "/api/recipes":
            return response({"items": [{"slug": "cached"}], "total": 1})
        calls += 1
        if fail:
            raise httpx.ReadTimeout("slow")
        return response({"name": "Cached", "recipeIngredient": []}, path=path)

    monkeypatch.setattr(recommendations, "mealie_get", fake_get)
    first = await build(db)
    second = await build(db)
    assert calls == 1
    assert first["recipe_cache_misses"] == 1
    assert second["recipe_cache_hits"] == 1
    refreshed = await build(db, refresh_cache=True)
    assert calls == 2 and refreshed["recipe_cache_misses"] == 1

    recommendations._recipe_cache.clear()
    fail = True
    failed = await build(db)
    failed_again = await build(db)
    assert calls == 3
    assert failed["recipe_cache_errors"] == 1
    assert failed_again["recipe_cache_hits"] == 1

    entry = recommendations._recipe_cache["cached"]
    recommendations._recipe_cache["cached"] = recommendations.RecipeCacheEntry(
        entry.detail,
        entry.error,
        0,
    )
    await build(db)
    assert calls == 4


@pytest.mark.asyncio
async def test_success_cache_expiry_refetches(monkeypatch, db):
    calls = 0

    async def fake_get(path, params=None):
        nonlocal calls
        if path == "/api/recipes":
            return response({"items": [{"slug": "ttl"}], "total": 1})
        calls += 1
        return response({"name": "TTL", "recipeIngredient": []}, path=path)

    monkeypatch.setattr(recommendations, "mealie_get", fake_get)
    monkeypatch.setattr(recommendations, "SUCCESS_CACHE_TTL_SECONDS", 0)
    await build(db)
    await build(db)
    assert calls == 2


@pytest.mark.asyncio
async def test_concurrent_same_slug_is_coalesced(monkeypatch):
    calls = 0

    async def fake_get(path, params=None):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return response({"name": "One"}, path=path)

    monkeypatch.setattr(recommendations, "mealie_get", fake_get)
    diagnostics = recommendations.CacheDiagnostics()
    semaphore = asyncio.Semaphore(8)
    results = await asyncio.gather(*(
        recommendations._fetch_cached_detail("same", semaphore, diagnostics)
        for _ in range(10)
    ))
    assert calls == 1
    assert diagnostics.misses == 1
    assert diagnostics.hits == 9
    assert all(detail and error is None for detail, error in results)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pages",
    [
        [({"items": [{"slug": "a"}], "totalPages": 2}), ({"items": [{"slug": "b"}], "totalPages": 2})],
        [({"items": [{"slug": "a"}], "total": 2}), ({"items": [{"slug": "b"}], "total": 2})],
        [({"items": [{"slug": "a"}], "next": "page-2"}), ({"items": [{"slug": "b"}], "next": None})],
    ],
)
async def test_pagination_metadata_variants(monkeypatch, pages):
    calls = 0

    async def fake_get(path, params=None):
        nonlocal calls
        payload = pages[min(calls, len(pages) - 1)]
        calls += 1
        return response(payload)

    monkeypatch.setattr(recommendations, "PAGE_SIZE", 1)
    monkeypatch.setattr(recommendations, "mealie_get", fake_get)
    result = await recommendations.fetch_all_summaries()
    assert [item["slug"] for item in result] == ["a", "b"]
    assert calls == 2


@pytest.mark.asyncio
async def test_pagination_stops_on_duplicate_empty_and_bad_metadata(monkeypatch):
    payloads = [
        {"items": [{"slug": "a"}], "next": True, "totalPages": 999999},
        {"items": [{"slug": "a"}], "next": True, "totalPages": 999999},
        {"items": [], "next": True},
    ]
    calls = 0

    async def fake_get(path, params=None):
        nonlocal calls
        payload = payloads[min(calls, len(payloads) - 1)]
        calls += 1
        return response(payload)

    monkeypatch.setattr(recommendations, "PAGE_SIZE", 1)
    monkeypatch.setattr(recommendations, "MAX_RECIPE_PAGES", 3)
    monkeypatch.setattr(recommendations, "mealie_get", fake_get)
    result = await recommendations.fetch_all_summaries()
    assert [item["slug"] for item in result] == ["a"]
    assert calls == 2


@pytest.mark.asyncio
async def test_pagination_stops_on_empty_page(monkeypatch):
    calls = 0

    async def fake_get(path, params=None):
        nonlocal calls
        calls += 1
        return response({"items": [], "next": True})

    monkeypatch.setattr(recommendations, "mealie_get", fake_get)
    assert await recommendations.fetch_all_summaries() == []
    assert calls == 1


@pytest.mark.asyncio
async def test_pagination_honors_maximum_page_guard(monkeypatch):
    calls = 0

    async def fake_get(path, params=None):
        nonlocal calls
        calls += 1
        return response({"items": [{"slug": f"page-{calls}"}], "next": True})

    monkeypatch.setattr(recommendations, "MAX_RECIPE_PAGES", 3)
    monkeypatch.setattr(recommendations, "mealie_get", fake_get)
    result = await recommendations.fetch_all_summaries()
    assert len(result) == 3
    assert calls == 3


def test_has_next_page_rejects_abnormal_metadata(monkeypatch):
    monkeypatch.setattr(recommendations, "PAGE_SIZE", 100)
    assert recommendations.has_next_page({"next": False}, 1, 1) is False
    assert recommendations.has_next_page({"next": 1}, 1, 1) is False
    assert recommendations.has_next_page({"totalPages": "many"}, 1, 1) is False


def test_recipe_cache_ttl_default(monkeypatch):
    monkeypatch.delenv("MEALIE_RECIPE_CACHE_TTL_SECONDS", raising=False)
    assert recommendations.DEFAULT_RECIPE_CACHE_TTL_SECONDS == 21_600
    assert recommendations._configured_recipe_cache_ttl_seconds() == 21_600


def test_recipe_cache_ttl_accepts_valid_custom_value(monkeypatch):
    monkeypatch.setenv("MEALIE_RECIPE_CACHE_TTL_SECONDS", "43200")
    assert recommendations._configured_recipe_cache_ttl_seconds() == 43_200


@pytest.mark.parametrize("value", ["299", "86401", "not-a-number"])
def test_recipe_cache_ttl_invalid_values_use_safe_default(monkeypatch, caplog, value):
    monkeypatch.setenv("MEALIE_RECIPE_CACHE_TTL_SECONDS", value)
    with caplog.at_level("WARNING"):
        result = recommendations._configured_recipe_cache_ttl_seconds()
    assert result == 21_600
    assert "using safe default 21600" in caplog.text
    assert value not in caplog.text


@pytest.mark.asyncio
async def test_manual_refresh_clears_success_and_failure_cache():
    recommendations._recipe_cache.update({
        "success": recommendations.RecipeCacheEntry({"name": "ok"}, None, 999999999),
        "failure": recommendations.RecipeCacheEntry(None, "safe error", 999999999),
    })
    await recommendations.clear_recipe_detail_cache()
    assert recommendations._recipe_cache == {}
    assert recommendations._recipe_inflight == {}
