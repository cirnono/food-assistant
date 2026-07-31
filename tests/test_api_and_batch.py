from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api_auth import read_api_token
from app.import_queue import ProcessAndAutoImportRequest, process_and_auto_import
from app.main import app


def test_llm_status_does_not_leak_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    api_key = "example-sensitive-provider-key"
    monkeypatch.setenv("LLM_API_KEY", api_key)
    read_api_token.cache_clear()
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/system/llm-status",
            headers={"X-Food-Assistant-Token": "example-development-token-00000000"},
        )
    assert response.status_code == 200
    assert response.json()["api_key_configured"] is True
    assert api_key not in response.text


def test_llm_test_requires_authentication() -> None:
    read_api_token.cache_clear()
    with TestClient(app) as client:
        response = client.post("/api/v1/system/llm-test")
    assert response.status_code == 401


def test_original_api_paths_still_exist() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/healthz",
        "/readyz",
        "/api/v1/inventory",
        "/api/v1/recommendations/preview",
        "/api/v1/ai/recipe/normalize",
        "/api/v1/integrations/ollama/status",
        "/api/v1/import-jobs",
        "/api/v1/import-jobs/{job_id}/process-and-auto-import",
    }
    assert expected <= set(paths)
    with TestClient(app) as client:
        response = client.get("/review")
    assert response.status_code == 200
    assert "Food Assistant" in response.text


class FakeSession:
    def rollback(self) -> None:
        pass

    def commit(self) -> None:
        pass

    def expire_all(self) -> None:
        pass


@pytest.mark.asyncio
async def test_batch_stops_on_infrastructure_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.import_queue as queue

    job = SimpleNamespace(id=1, name="test", status="approved")
    calls = 0

    async def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise HTTPException(status_code=503, detail="CUDA out of memory")

    monkeypatch.setattr(queue, "get_job_or_404", lambda *args: job)
    monkeypatch.setattr(queue, "requeue_ollama_infrastructure_failures", lambda *args: [])
    monkeypatch.setattr(queue, "process_next_import_item", fail_once)
    monkeypatch.setattr(queue, "update_job_status", lambda *args: None)
    monkeypatch.setattr(queue, "job_status_counts", lambda *args: {"queued": 1})
    monkeypatch.setattr(
        queue, "unload_ollama_model", lambda: pytest.fail("unload not requested")
    )
    result = await process_and_auto_import(
        1,
        ProcessAndAutoImportRequest(count=5, unload_model_after_batch=False),
        FakeSession(),
    )
    assert calls == 1
    assert result["stopped_early"] is True
    assert result["stop_reason"] == "ollama_infrastructure_error"
