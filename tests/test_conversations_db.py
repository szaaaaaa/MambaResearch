"""Conversations + segments DB 行为测试。

覆盖：schema 幂等初始化、CRUD、按 project_id 过滤、segment 自增 index、
级联删除、close_active_segment。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.projects.conversations import (
    add_segment,
    close_active_segment,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_by_project,
    list_segments,
    update_title,
)
from src.server.projects.db import MambaDb, set_db_for_tests
from src.server.routes.conversations import router as conv_router


@pytest.fixture
def temp_db(tmp_path: Path):
    db = MambaDb(db_path=tmp_path / "mamba.db")
    set_db_for_tests(db)
    db.connect()  # 触发 schema init
    yield db
    set_db_for_tests(None)


def test_schema_init_idempotent(tmp_path: Path) -> None:
    db = MambaDb(db_path=tmp_path / "mamba.db")
    db.connect()
    # 关闭重连不抛错
    db.close()
    db.connect()
    db.close()


def test_create_and_list_conversation(temp_db: MambaDb) -> None:
    conv = create_conversation(project_id="proj-1", title="第一个")
    assert conv.id
    assert conv.project_id == "proj-1"
    assert conv.title == "第一个"

    rows = list_by_project("proj-1")
    assert len(rows) == 1
    assert rows[0].id == conv.id


def test_list_filters_by_project(temp_db: MambaDb) -> None:
    create_conversation(project_id="proj-1", title="a")
    create_conversation(project_id="proj-2", title="b")
    create_conversation(project_id="proj-1", title="c")
    assert len(list_by_project("proj-1")) == 2
    assert len(list_by_project("proj-2")) == 1


def test_list_orders_by_last_active_desc(temp_db: MambaDb) -> None:
    a = create_conversation(project_id="p", title="a")
    b = create_conversation(project_id="p", title="b")
    c = create_conversation(project_id="p", title="c")
    # update_title 会刷新 last_active_at
    update_title(a.id, "a-updated")
    rows = list_by_project("p")
    assert rows[0].id == a.id
    assert {r.id for r in rows} == {a.id, b.id, c.id}


def test_get_conversation_returns_none_for_missing(temp_db: MambaDb) -> None:
    assert get_conversation("nonexistent") is None


def test_delete_conversation_cascades_segments(temp_db: MambaDb) -> None:
    conv = create_conversation(project_id="p")
    add_segment(conversation_id=conv.id, backend="claude", cli_session_id="s1")
    add_segment(conversation_id=conv.id, backend="codex", cli_session_id="s2")
    assert len(list_segments(conv.id)) == 2

    deleted = delete_conversation(conv.id)
    assert deleted is True
    assert get_conversation(conv.id) is None
    assert list_segments(conv.id) == []


def test_delete_unknown_returns_false(temp_db: MambaDb) -> None:
    assert delete_conversation("nonexistent") is False


def test_segment_index_auto_increments(temp_db: MambaDb) -> None:
    conv = create_conversation(project_id="p")
    s1 = add_segment(conversation_id=conv.id, backend="claude", cli_session_id="cs1")
    s2 = add_segment(conversation_id=conv.id, backend="codex", cli_session_id="cs2")
    s3 = add_segment(conversation_id=conv.id, backend="claude", cli_session_id="cs3")
    assert (s1.segment_index, s2.segment_index, s3.segment_index) == (1, 2, 3)


def test_segment_invalid_backend_rejected(temp_db: MambaDb) -> None:
    conv = create_conversation(project_id="p")
    with pytest.raises(ValueError):
        add_segment(conversation_id=conv.id, backend="other", cli_session_id="x")


def test_close_active_segment_only_closes_open(temp_db: MambaDb) -> None:
    conv = create_conversation(project_id="p")
    s1 = add_segment(conversation_id=conv.id, backend="claude", cli_session_id="cs1")
    closed = close_active_segment(conv.id)
    assert closed is True
    rows = list_segments(conv.id)
    assert rows[0].ended_at is not None

    # 第二次关——已无 active 段
    closed_again = close_active_segment(conv.id)
    assert closed_again is False


def test_route_create_and_list(temp_db: MambaDb) -> None:
    app = FastAPI()
    app.include_router(conv_router)
    client = TestClient(app)

    create = client.post("/api/conversations", json={"project_id": "p1", "title": "t"})
    assert create.status_code == 200
    conv_id = create.json()["id"]

    listed = client.get("/api/conversations", params={"project_id": "p1"})
    assert listed.status_code == 200
    assert any(c["id"] == conv_id for c in listed.json()["conversations"])


def test_route_create_requires_project_id(temp_db: MambaDb) -> None:
    app = FastAPI()
    app.include_router(conv_router)
    client = TestClient(app)
    resp = client.post("/api/conversations", json={"title": "x"})
    assert resp.status_code == 400


def test_route_delete_returns_404_for_missing(temp_db: MambaDb) -> None:
    app = FastAPI()
    app.include_router(conv_router)
    client = TestClient(app)
    resp = client.delete("/api/conversations/nope")
    assert resp.status_code == 404


def test_route_segments_returns_404_for_missing_conv(temp_db: MambaDb) -> None:
    app = FastAPI()
    app.include_router(conv_router)
    client = TestClient(app)
    resp = client.get("/api/conversations/nope/segments")
    assert resp.status_code == 404


def test_route_messages_returns_404_for_missing_conv(temp_db: MambaDb) -> None:
    app = FastAPI()
    app.include_router(conv_router)
    client = TestClient(app)
    resp = client.get("/api/conversations/nope/messages")
    assert resp.status_code == 404


def test_route_messages_returns_messages_in_order(temp_db: MambaDb) -> None:
    """Hybrid Master Transcript T3 — GET /api/conversations/{id}/messages
    返回该 conversation 的全部 messages，按 created_at 升序。"""
    from src.server.projects.messages_store import append_message

    app = FastAPI()
    app.include_router(conv_router)
    client = TestClient(app)

    conv = create_conversation(project_id="proj-x", title="msgs")
    append_message(
        conversation_id=conv.id, role="user", text="hi", served_by="user"
    )
    append_message(
        conversation_id=conv.id,
        role="assistant",
        text="hello",
        served_by="claude",
    )

    resp = client.get(f"/api/conversations/{conv.id}/messages")
    assert resp.status_code == 200
    body = resp.json()
    assert "messages" in body
    msgs = body["messages"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["text"] == "hi"
    assert msgs[0]["served_by"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["text"] == "hello"
    assert msgs[1]["served_by"] == "claude"
    # compacted 字段一定存在（前端 hydrate 用）
    assert msgs[0]["compacted"] is False
    assert msgs[1]["compacted"] is False


def test_route_patch_title(temp_db: MambaDb) -> None:
    app = FastAPI()
    app.include_router(conv_router)
    client = TestClient(app)
    create = client.post("/api/conversations", json={"project_id": "p"})
    cid = create.json()["id"]
    patch = client.patch(f"/api/conversations/{cid}", json={"title": "新名"})
    assert patch.status_code == 200
    assert patch.json()["title"] == "新名"
