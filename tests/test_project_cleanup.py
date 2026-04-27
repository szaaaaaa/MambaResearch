"""DELETE /api/projects/{id} 级联清 mamba.db 行为测试。

只覆盖 cleanup_project_data 单元——HTTP 路由层 cleanup → registry.delete
顺序由 routes/projects.py 直接保证，集成测试单独跑。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.server.projects.cleanup import cleanup_project_data
from src.server.projects.conversations import (
    add_segment,
    create_conversation,
)
from src.server.projects.db import MambaDb, set_db_for_tests
from src.server.projects.messages_store import append_message


@pytest.fixture
def temp_db(tmp_path: Path):
    db = MambaDb(db_path=tmp_path / "mamba.db")
    set_db_for_tests(db)
    db.connect()
    yield db
    set_db_for_tests(None)


def _insert_mcp_call(db: MambaDb, *, conversation_id: str, backend: str) -> str:
    import uuid

    call_id = uuid.uuid4().hex
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO mcp_calls "
            "(id, conversation_id, backend, server_name, tool_name, "
            "input_json, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (call_id, conversation_id, backend, "mamba_workspace", "scan", "{}", int(time.time())),
        )
    return call_id


def _insert_experiment_run(db: MambaDb, *, project_id: str) -> str:
    import uuid

    run_id = uuid.uuid4().hex
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO experiment_runs "
            "(id, project_id, script_path, args_json, started_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, project_id, "/tmp/x.py", "[]", int(time.time()), "running"),
        )
    return run_id


def _count(db: MambaDb, table: str, where: str = "", params: tuple = ()) -> int:
    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM {table} {where}", params)
        return cur.fetchone()["n"]


def test_cleanup_empty_project_returns_zeros(temp_db: MambaDb) -> None:
    """无任何关联数据时清理应返全零，不抛异常。"""
    summary = cleanup_project_data("project-with-nothing")
    assert summary.to_dict() == {
        "conversations": 0,
        "conversation_segments": 0,
        "messages": 0,
        "mcp_calls": 0,
        "experiment_runs": 0,
    }


def test_cleanup_full_cascade(temp_db: MambaDb) -> None:
    """所有关联表的行都按 project_id / conversation_id 链清掉。"""
    pid = "proj-target"
    other_pid = "proj-other"  # 旁路：另一项目数据不能误伤

    # target project：1 conversation + 2 segments + 3 messages + 2 mcp_calls + 1 exp run
    conv = create_conversation(project_id=pid, title="t", backend="claude")
    add_segment(conversation_id=conv.id, backend="claude", cli_session_id="sid-1")
    add_segment(conversation_id=conv.id, backend="codex", cli_session_id="sid-2")
    append_message(conversation_id=conv.id, role="user", text="一", served_by="user")
    append_message(conversation_id=conv.id, role="assistant", text="一回", served_by="claude")
    append_message(conversation_id=conv.id, role="user", text="二", served_by="user")
    _insert_mcp_call(temp_db, conversation_id=conv.id, backend="claude")
    _insert_mcp_call(temp_db, conversation_id=conv.id, backend="codex")
    _insert_experiment_run(temp_db, project_id=pid)

    # other project：1 conversation + 1 message + 1 exp run（不能被误删）
    other_conv = create_conversation(project_id=other_pid, title="other", backend="codex")
    add_segment(
        conversation_id=other_conv.id, backend="codex", cli_session_id="sid-other"
    )
    append_message(
        conversation_id=other_conv.id, role="user", text="保留", served_by="user"
    )
    _insert_experiment_run(temp_db, project_id=other_pid)

    summary = cleanup_project_data(pid)
    assert summary.conversations == 1
    assert summary.conversation_segments == 2
    assert summary.messages == 3
    assert summary.mcp_calls == 2
    assert summary.experiment_runs == 1

    # target 全清
    assert _count(temp_db, "conversations", "WHERE project_id = ?", (pid,)) == 0
    assert _count(
        temp_db, "messages", "WHERE conversation_id = ?", (conv.id,)
    ) == 0
    assert _count(
        temp_db, "conversation_segments", "WHERE conversation_id = ?", (conv.id,)
    ) == 0
    assert _count(
        temp_db, "mcp_calls", "WHERE conversation_id = ?", (conv.id,)
    ) == 0
    assert _count(temp_db, "experiment_runs", "WHERE project_id = ?", (pid,)) == 0

    # 旁路 project 数据完整保留
    assert _count(temp_db, "conversations", "WHERE project_id = ?", (other_pid,)) == 1
    assert _count(
        temp_db, "messages", "WHERE conversation_id = ?", (other_conv.id,)
    ) == 1
    assert _count(
        temp_db, "conversation_segments", "WHERE conversation_id = ?", (other_conv.id,)
    ) == 1
    assert _count(temp_db, "experiment_runs", "WHERE project_id = ?", (other_pid,)) == 1


def test_cleanup_only_experiment_runs(temp_db: MambaDb) -> None:
    """没有 conversation 但有 experiment_runs 的 project（譬如直接调实验 MCP）也要清掉。"""
    pid = "proj-exp-only"
    _insert_experiment_run(temp_db, project_id=pid)
    _insert_experiment_run(temp_db, project_id=pid)
    summary = cleanup_project_data(pid)
    assert summary.experiment_runs == 2
    assert summary.conversations == 0
    assert _count(temp_db, "experiment_runs", "WHERE project_id = ?", (pid,)) == 0
