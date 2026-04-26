"""LibraryTab 后端路由测试。"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.routes.library import router as library_router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(library_router)
    yield TestClient(app)


def test_collections_returns_500_or_502_when_no_creds(monkeypatch, client):
    monkeypatch.delenv("ZOTERO_USER_ID", raising=False)
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    # Make sure repo .env doesn't satisfy creds either
    from pathlib import Path
    monkeypatch.setattr(
        "src.server.integrations.zotero.credentials.ENV_PATH",
        Path("/absent.env"),
    )
    resp = client.get("/api/library/zotero/collections")
    assert resp.status_code == 502
    assert "ZOTERO" in resp.json()["detail"]


def test_collections_proxies_to_client(monkeypatch, client):
    monkeypatch.setenv("ZOTERO_USER_ID", "12345")
    monkeypatch.setenv("ZOTERO_API_KEY", "k")
    fake_collections = [{"key": "C1", "name": "Inbox"}]
    with patch(
        "src.server.routes.library.ZoteroClient",
        return_value=type("FC", (), {"list_collections": lambda self: fake_collections})(),
    ):
        resp = client.get("/api/library/zotero/collections")
    assert resp.status_code == 200
    assert resp.json() == {"collections": fake_collections}


def test_items_proxies_to_client_with_query_and_limit(monkeypatch, client):
    monkeypatch.setenv("ZOTERO_USER_ID", "12345")
    monkeypatch.setenv("ZOTERO_API_KEY", "k")
    received = {}

    class FakeClient:
        def search(self, query, limit=20):
            received["query"] = query
            received["limit"] = limit
            return [{"key": "I1", "title": "Mamba"}]

    with patch("src.server.routes.library.ZoteroClient", return_value=FakeClient()):
        resp = client.get("/api/library/zotero/items", params={"query": "ssm", "limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"][0]["key"] == "I1"
    assert received == {"query": "ssm", "limit": 5}


def test_items_returns_502_on_client_failure(monkeypatch, client):
    monkeypatch.setenv("ZOTERO_USER_ID", "12345")
    monkeypatch.setenv("ZOTERO_API_KEY", "k")

    class BoomClient:
        def search(self, query, limit=20):
            raise RuntimeError("network down")

    with patch("src.server.routes.library.ZoteroClient", return_value=BoomClient()):
        resp = client.get("/api/library/zotero/items", params={"query": "x"})
    assert resp.status_code == 502
    assert "network down" in resp.json()["detail"]
