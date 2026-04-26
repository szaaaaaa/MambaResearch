"""mamba_history MCP server 行为测试。

直接调内部 ``_call_*`` handler，不真起 stdio 子进程——用同 conftest fixture 注入
临时 mamba.db + 临时 projects.json，验 search / get 跨 project 边界保护。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from src.server.integrations.mamba_history import mcp_server as mh
from src.server.projects.conversations import create_conversation
from src.server.projects.db import MambaDb, set_db_for_tests
from src.server.projects.messages_store import append_message


@pytest.fixture
def temp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """注入临时 mamba.db + projects.json + ACTIVE_PROJECT_PATH env。"""
    db_path = tmp_path / "mamba.db"
    db = MambaDb(db_path=db_path)
    set_db_for_tests(db)
    db.connect()

    project_path = tmp_path / "active-proj"
    project_path.mkdir()
    project_id = "proj-active-1"
    registry_path = tmp_path / "projects.json"
    registry_path.write_text(
        json.dumps(
            {
                "projects": [
                    {"id": project_id, "name": "active", "path": str(project_path)},
                    {"id": "proj-other", "name": "other", "path": str(tmp_path / "other")},
                ],
                "active_project_id": project_id,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(mh.ACTIVE_PROJECT_ENV_VAR, str(project_path))
    monkeypatch.setattr(mh, "_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(mh, "_DB_PATH", db_path)

    yield {"project_id": project_id, "tmp_path": tmp_path}
    set_db_for_tests(None)


def test_resolve_active_project_id_ok(temp_env) -> None:
    pid, err = mh._resolve_active_project_id()
    assert err is None
    assert pid == temp_env["project_id"]


def test_resolve_active_project_id_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(mh.ACTIVE_PROJECT_ENV_VAR, raising=False)
    pid, err = mh._resolve_active_project_id()
    assert pid is None
    assert "MAMBA_ACTIVE_PROJECT_PATH" in (err or "")


def test_search_conversations_empty_query_returns_recent(temp_env) -> None:
    pid = temp_env["project_id"]
    c1 = create_conversation(project_id=pid, title="一", backend="claude")
    c2 = create_conversation(project_id=pid, title="二", backend="codex")
    out = mh._call_search_conversations({"query": "", "k": 10}, pid)
    assert out["isError"] is False
    convs = out["structuredContent"]["conversations"]
    ids = {c["conversation_id"] for c in convs}
    assert ids == {c1.id, c2.id}


def test_search_conversations_matches_title(temp_env) -> None:
    pid = temp_env["project_id"]
    create_conversation(project_id=pid, title="实验设计讨论", backend="claude")
    create_conversation(project_id=pid, title="文献综述", backend="codex")
    out = mh._call_search_conversations({"query": "实验", "k": 5}, pid)
    convs = out["structuredContent"]["conversations"]
    assert len(convs) == 1
    assert convs[0]["title"] == "实验设计讨论"
    assert convs[0]["matched_in"] == "title"


def test_search_conversations_matches_message_text(temp_env) -> None:
    pid = temp_env["project_id"]
    conv = create_conversation(project_id=pid, title="无关标题", backend="claude")
    append_message(
        conversation_id=conv.id,
        role="user",
        text="想跑一个 transformer 在 cifar10 上的 baseline",
        served_by="user",
    )
    out = mh._call_search_conversations({"query": "transformer", "k": 5}, pid)
    convs = out["structuredContent"]["conversations"]
    assert len(convs) == 1
    assert convs[0]["conversation_id"] == conv.id
    assert "transformer" in convs[0]["snippet"]


def test_search_conversations_excludes_other_project(temp_env) -> None:
    pid = temp_env["project_id"]
    create_conversation(project_id=pid, title="active project conv", backend="claude")
    create_conversation(project_id="proj-other", title="active project conv", backend="claude")
    out = mh._call_search_conversations({"query": "active", "k": 5}, pid)
    convs = out["structuredContent"]["conversations"]
    # 仅本 project 的命中
    assert len(convs) == 1


def test_get_conversation_messages_returns_last_n_ascending(temp_env) -> None:
    import time

    pid = temp_env["project_id"]
    conv = create_conversation(project_id=pid, title="t", backend="claude")
    append_message(conversation_id=conv.id, role="user", text="一", served_by="user")
    time.sleep(1.01)
    append_message(conversation_id=conv.id, role="assistant", text="一回", served_by="claude")
    time.sleep(1.01)
    append_message(conversation_id=conv.id, role="user", text="二", served_by="user")

    out = mh._call_get_conversation_messages(
        {"conversation_id": conv.id, "last_n": 2}, pid
    )
    assert out["isError"] is False
    msgs = out["structuredContent"]["messages"]
    assert [m["text"] for m in msgs] == ["一回", "二"]
    assert out["structuredContent"]["returned_count"] == 2


def test_get_conversation_messages_rejects_cross_project(temp_env) -> None:
    pid = temp_env["project_id"]
    other = create_conversation(project_id="proj-other", title="x", backend="claude")
    out = mh._call_get_conversation_messages(
        {"conversation_id": other.id, "last_n": 5}, pid
    )
    assert out["isError"] is True
    assert "属于其它 project" in out["content"][0]["text"]


def test_get_conversation_messages_unknown_conv(temp_env) -> None:
    pid = temp_env["project_id"]
    out = mh._call_get_conversation_messages(
        {"conversation_id": "never-existed", "last_n": 5}, pid
    )
    assert out["isError"] is True
    assert "不存在" in out["content"][0]["text"]


def test_default_mcp_config_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAMBA_HISTORY_MCP_DISABLED", "1")
    assert mh.default_mcp_config(Path(".")) == {}


def test_default_mcp_config_default_includes_server() -> None:
    cfg = mh.default_mcp_config(Path("."))
    assert mh.DEFAULT_SERVER_KEY in cfg
    entry = cfg[mh.DEFAULT_SERVER_KEY]
    assert entry["type"] == "stdio"
    assert entry["args"][:2] == ["-m", "src.server.integrations.mamba_history.mcp_server"]
