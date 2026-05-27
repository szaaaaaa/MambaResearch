"""Claude Code 会话 SQLite 持久化（``ClaudeCodeStore``）的单元测试。

CLI PTY pivot 后，``SessionManager`` / REST API 相关测试一并移除；本文件只保留纯存储层 CRUD 测试——storage.py 仍是
聊天历史 mirror 的事实源（PTY tee + 新简化的 GET 端点都依赖它）。
"""

from __future__ import annotations

import pytest

from src.server.claude_code.storage import ClaudeCodeStore


# ---------------------------------------------------------------------------
# ClaudeCodeStore 纯存储 CRUD
# ---------------------------------------------------------------------------


def test_store_insert_and_get_roundtrip(tmp_path):
    store = ClaudeCodeStore(tmp_path / "cc.db")
    store.insert_session(
        session_id="abc",
        cwd=str(tmp_path),
        model="claude-opus-4-7",
        permission_mode="default",
        add_dirs=["/extra"],
    )
    row = store.get_session("abc")
    assert row is not None
    assert row.id == "abc"
    assert row.cwd == str(tmp_path)
    assert row.model == "claude-opus-4-7"
    assert row.permission_mode == "default"
    assert row.add_dirs == ["/extra"]
    assert row.message_count == 0
    store.close()


def test_store_append_message_sequence_is_per_session(tmp_path):
    store = ClaudeCodeStore(tmp_path / "cc.db")
    store.insert_session(
        session_id="s1", cwd=str(tmp_path), model=None, permission_mode="default"
    )
    store.insert_session(
        session_id="s2", cwd=str(tmp_path), model=None, permission_mode="default"
    )
    seq1a = store.append_message("s1", event_type="cc_message", payload={"k": 1})
    seq1b = store.append_message("s1", event_type="cc_message", payload={"k": 2})
    seq2a = store.append_message("s2", event_type="cc_message", payload={"k": 3})
    assert seq1a == 0 and seq1b == 1 and seq2a == 0
    msgs1 = store.get_messages("s1")
    msgs2 = store.get_messages("s2")
    assert [m.sequence for m in msgs1] == [0, 1]
    assert [m.payload["k"] for m in msgs1] == [1, 2]
    assert [m.sequence for m in msgs2] == [0]
    # message_count 被同步更新
    assert store.get_session("s1").message_count == 2
    assert store.get_session("s2").message_count == 1
    store.close()


def test_store_append_to_missing_session_returns_minus_one(tmp_path):
    store = ClaudeCodeStore(tmp_path / "cc.db")
    seq = store.append_message("ghost", event_type="cc_message", payload={})
    assert seq == -1
    store.close()


def test_store_accumulate_usage_sums(tmp_path):
    store = ClaudeCodeStore(tmp_path / "cc.db")
    store.insert_session(
        session_id="s", cwd=str(tmp_path), model=None, permission_mode="default"
    )
    store.accumulate_usage("s", input_tokens=3, output_tokens=5, cost_usd=0.01)
    store.accumulate_usage("s", input_tokens=2, output_tokens=1, cost_usd=0.02)
    row = store.get_session("s")
    assert row.total_input_tokens == 5
    assert row.total_output_tokens == 6
    assert row.total_cost_usd == pytest.approx(0.03)
    store.close()


def test_store_clear_messages_keeps_session(tmp_path):
    store = ClaudeCodeStore(tmp_path / "cc.db")
    store.insert_session(
        session_id="s", cwd=str(tmp_path), model=None, permission_mode="default"
    )
    store.append_message("s", event_type="cc_message", payload={})
    store.append_message("s", event_type="cc_message", payload={})
    deleted = store.clear_messages("s")
    assert deleted == 2
    assert store.get_messages("s") == []
    # session 行还在，count 归零
    assert store.get_session("s").message_count == 0
    store.close()


def test_store_delete_cascades_messages(tmp_path):
    store = ClaudeCodeStore(tmp_path / "cc.db")
    store.insert_session(
        session_id="s", cwd=str(tmp_path), model=None, permission_mode="default"
    )
    store.append_message("s", event_type="cc_message", payload={})
    assert store.delete_session("s") is True
    assert store.get_session("s") is None
    assert store.get_messages("s") == []
    store.close()
