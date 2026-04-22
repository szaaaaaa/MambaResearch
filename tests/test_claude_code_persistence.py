"""Claude Code 会话 SQLite 持久化 + 刷新恢复测试（Task 8）。

覆盖三层：

1. ``ClaudeCodeStore`` 纯存储 CRUD——不依赖 SDK，直接建 sqlite 文件验证
2. ``SessionManager`` 配合 store 的语义——create 落库、delete 级联、idle
   evict 保留 DB 行、``record_event`` 对 result 自动累加 usage、
   ``get_or_restore`` 从 DB 行按 ``resume`` 重建 SDK client
3. REST 层——``GET /sessions`` 合并 memory+DB、``GET /sessions/{id}/messages``
   回灌事件流、send_message 对已 evict 会话自动恢复
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

import src.server.claude_code.session_manager as sm_module
from src.server.claude_code.storage import ClaudeCodeStore

import app as app_module

from tests.test_claude_code_session import FakeClient


# ---------------------------------------------------------------------------
# ClaudeCodeStore 纯存储
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


# ---------------------------------------------------------------------------
# SessionManager + store 集成
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_sdk_with_store(monkeypatch, tmp_path):
    """注入 FakeClient + 全新 ClaudeCodeStore 到 tmp_path，覆盖全局 session_manager。"""
    FakeClient.created = []
    monkeypatch.setattr(sm_module, "ClaudeSDKClient", FakeClient)
    store = ClaudeCodeStore(tmp_path / "cc.db")
    monkeypatch.setattr(sm_module.session_manager, "_sessions", {})
    monkeypatch.setattr(sm_module.session_manager, "_lock", asyncio.Lock())
    monkeypatch.setattr(sm_module.session_manager, "_store", store)
    yield store
    store.close()


def test_session_manager_create_persists_row(fake_sdk_with_store):
    async def run():
        mgr = sm_module.session_manager
        session = await mgr.create(cwd=".", model="claude-sonnet-4-6")
        row = fake_sdk_with_store.get_session(session.id)
        assert row is not None
        assert row.cwd.endswith(".") or row.cwd  # resolved by caller/store as-is
        assert row.model == "claude-sonnet-4-6"
        assert row.permission_mode == "default"

    asyncio.run(run())


def test_session_manager_delete_removes_db_row(fake_sdk_with_store):
    async def run():
        mgr = sm_module.session_manager
        session = await mgr.create(cwd=".")
        assert fake_sdk_with_store.get_session(session.id) is not None
        assert await mgr.delete(session.id) is True
        assert fake_sdk_with_store.get_session(session.id) is None

    asyncio.run(run())


def test_session_manager_idle_evict_keeps_db_row(monkeypatch, tmp_path):
    """TTL 触发 evict 后 DB 行仍在，供 get_or_restore 重建。"""
    FakeClient.created = []
    monkeypatch.setattr(sm_module, "ClaudeSDKClient", FakeClient)
    store = ClaudeCodeStore(tmp_path / "cc.db")

    async def run():
        mgr = sm_module.SessionManager(
            idle_ttl_sec=0.1, sweep_interval_sec=0.04, store=store
        )
        try:
            session = await mgr.create(cwd=".")
            await asyncio.sleep(0.3)
            # 内存注册表被 sweep 清掉
            assert mgr.get(session.id) is None
            # DB 行保留
            assert store.get_session(session.id) is not None
        finally:
            await mgr.shutdown()

    asyncio.run(run())


def test_record_event_persists_and_accumulates(fake_sdk_with_store):
    async def run():
        mgr = sm_module.session_manager
        session = await mgr.create(cwd=".")
        mgr.record_event(
            session.id, event_type="cc_user_prompt", payload={"text": "hi"}
        )
        # result 事件带 usage → 触发 accumulate
        mgr.record_event(
            session.id,
            event_type="cc_message",
            payload={
                "type": "result",
                "usage": {"input_tokens": 10, "output_tokens": 20},
                "total_cost_usd": 0.05,
            },
        )
        msgs = fake_sdk_with_store.get_messages(session.id)
        assert len(msgs) == 2
        row = fake_sdk_with_store.get_session(session.id)
        assert row.total_input_tokens == 10
        assert row.total_output_tokens == 20
        assert row.total_cost_usd == pytest.approx(0.05)

    asyncio.run(run())


def test_get_or_restore_rebuilds_from_db(fake_sdk_with_store):
    """被 evict 后 DB 仍有行 → get_or_restore 以 sdk_resume=True 建新 client。"""

    async def run():
        mgr = sm_module.session_manager
        session = await mgr.create(cwd=".", model="claude-haiku-4-5-20251001")
        sid = session.id
        # 模拟 idle evict：手动清空内存注册表
        async with mgr._lock:
            mgr._sessions.clear()
        restored = await mgr.get_or_restore(sid)
        assert restored is not None
        assert restored.id == sid
        assert restored.model == "claude-haiku-4-5-20251001"
        # 恢复路径应传 resume=session_id，不传 session_id=
        fake = FakeClient.created[-1]
        opts = fake.options
        # ClaudeAgentOptions 是 dataclass；resume 字段为我们的 uuid
        assert getattr(opts, "resume", None) == sid
        # create 路径的初始 options 走 session_id=；恢复路径走 resume=
        # 验证两者不会同时设置
        assert getattr(opts, "session_id", None) in (None, "")

    asyncio.run(run())


def test_get_or_restore_returns_none_for_unknown(fake_sdk_with_store):
    async def run():
        mgr = sm_module.session_manager
        assert await mgr.get_or_restore("never-existed") is None

    asyncio.run(run())


# ---------------------------------------------------------------------------
# REST 路由
# ---------------------------------------------------------------------------


def test_list_sessions_includes_running_flag(fake_sdk_with_store):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        data = client.get("/api/claude-code/sessions").json()
        row = next(s for s in data["sessions"] if s["id"] == sid)
        assert row["running"] is True
        # DB 额外字段透传
        assert "message_count" in row and "total_cost_usd" in row
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_get_session_messages_returns_history(fake_sdk_with_store):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        # 跑一轮 send_message 让 DB 里留事件
        with client.stream(
            "POST",
            f"/api/claude-code/sessions/{sid}/messages",
            json={"prompt": "hello"},
        ) as resp:
            b"".join(resp.iter_bytes())
        data = client.get(f"/api/claude-code/sessions/{sid}/messages").json()
        assert data["session"]["id"] == sid
        types = [row["event_type"] for row in data["messages"]]
        # 至少包含 user_prompt + 若干 cc_message + cc_finished
        assert "cc_user_prompt" in types
        assert "cc_message" in types
        assert "cc_finished" in types
        # sequence 从 0 开始递增
        seqs = [row["sequence"] for row in data["messages"]]
        assert seqs == list(range(len(seqs)))
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_get_session_messages_unknown_id_returns_404(fake_sdk_with_store):
    client = TestClient(app_module.app)
    resp = client.get("/api/claude-code/sessions/ghost/messages")
    assert resp.status_code == 404


def test_send_message_restores_evicted_session(fake_sdk_with_store):
    """已 evict 但 DB 仍有行的会话，send_message 应触发 get_or_restore 成功。"""
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        # 手动模拟 evict：清空内存注册表但保留 DB 行
        async def evict():
            async with sm_module.session_manager._lock:
                sm_module.session_manager._sessions.clear()

        asyncio.run(evict())
        assert fake_sdk_with_store.get_session(sid) is not None

        with client.stream(
            "POST",
            f"/api/claude-code/sessions/{sid}/messages",
            json={"prompt": "after evict"},
        ) as resp:
            assert resp.status_code == 200
            b"".join(resp.iter_bytes())
        # 新 client 被创建（resume 路径）
        assert any(
            getattr(c.options, "resume", None) == sid for c in FakeClient.created
        )
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")
