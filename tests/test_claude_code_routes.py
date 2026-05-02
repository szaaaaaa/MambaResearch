"""``routes/claude_code.py`` 简化版（plan 2026-05-01 Task 6a 后）的端点测试。

只覆盖会话列表 popover 用的 4 个端点：

- ``GET    /api/claude-code/sessions``
- ``GET    /api/claude-code/sessions/{id}/messages``
- ``PATCH  /api/claude-code/sessions/{id}``（重命名 title）
- ``DELETE /api/claude-code/sessions/{id}``

PTY 实时聊天走 ``WS /api/terminal/claude``，与本路由独立。
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.claude_code.storage import ClaudeCodeStore
from src.server.routes import claude_code as claude_code_routes


@pytest.fixture
def app_with_store(tmp_path, monkeypatch):
    """新建空 sqlite store 注入到路由模块的 module-level _store 变量。"""
    store = ClaudeCodeStore(tmp_path / "cc.db")
    monkeypatch.setattr(claude_code_routes, "_store", store)
    app = FastAPI()
    app.include_router(claude_code_routes.router)
    yield app, store
    store.close()


def _seed_session(store: ClaudeCodeStore, session_id: str, *, title: str | None = None) -> None:
    store.insert_session(
        session_id=session_id,
        cwd=".",
        model="claude-opus-4-7",
        permission_mode="default",
        title=title,
    )


def test_list_sessions_returns_db_rows(app_with_store):
    app, store = app_with_store
    _seed_session(store, "s1", title="第一条")
    _seed_session(store, "s2", title="第二条")
    client = TestClient(app)

    resp = client.get("/api/claude-code/sessions")
    assert resp.status_code == 200
    data = resp.json()
    ids = {s["id"] for s in data["sessions"]}
    assert ids == {"s1", "s2"}
    titles = {s["id"]: s["title"] for s in data["sessions"]}
    assert titles == {"s1": "第一条", "s2": "第二条"}
    # is_running 在 PTY 模式下永远 False
    assert all(s["is_running"] is False for s in data["sessions"])


def test_get_messages_404_for_unknown(app_with_store):
    app, _ = app_with_store
    client = TestClient(app)
    resp = client.get("/api/claude-code/sessions/missing/messages")
    assert resp.status_code == 404


def test_get_messages_returns_appended_events(app_with_store):
    app, store = app_with_store
    _seed_session(store, "s1")
    store.append_message("s1", event_type="cc_message", payload={"role": "assistant"})
    store.append_message("s1", event_type="cc_finished", payload={"status": "ok"})

    client = TestClient(app)
    resp = client.get("/api/claude-code/sessions/s1/messages")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session"]["id"] == "s1"
    seqs = [m["sequence"] for m in data["messages"]]
    assert seqs == [0, 1]
    types = [m["event_type"] for m in data["messages"]]
    assert types == ["cc_message", "cc_finished"]


def test_patch_title_updates_row(app_with_store):
    app, store = app_with_store
    _seed_session(store, "s1", title="旧标题")
    client = TestClient(app)

    resp = client.patch(
        "/api/claude-code/sessions/s1", json={"title": "新标题"}
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "新标题"
    # 落库验证
    assert store.get_session("s1").title == "新标题"


def test_patch_title_empty_string_clears(app_with_store):
    app, store = app_with_store
    _seed_session(store, "s1", title="something")
    client = TestClient(app)

    resp = client.patch("/api/claude-code/sessions/s1", json={"title": "   "})
    assert resp.status_code == 200
    assert resp.json()["title"] is None


def test_patch_unknown_session_404(app_with_store):
    app, _ = app_with_store
    client = TestClient(app)
    resp = client.patch("/api/claude-code/sessions/ghost", json={"title": "x"})
    assert resp.status_code == 404


def test_delete_session_cascades_messages(app_with_store):
    app, store = app_with_store
    _seed_session(store, "s1")
    store.append_message("s1", event_type="cc_message", payload={})
    client = TestClient(app)

    resp = client.delete("/api/claude-code/sessions/s1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert store.get_session("s1") is None
    assert store.get_messages("s1") == []


def test_delete_unknown_session_404(app_with_store):
    app, _ = app_with_store
    client = TestClient(app)
    resp = client.delete("/api/claude-code/sessions/ghost")
    assert resp.status_code == 404
