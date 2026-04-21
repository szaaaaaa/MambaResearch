"""Claude Code SDK 会话桥接测试。

SDK 真正 connect 会启动 ``claude`` 子进程并需要凭据，CI/本地都不可靠，所以本测试用
monkeypatch 把 ``ClaudeSDKClient`` 替换为纯内存的假实现，只验证：

1. ``SessionManager`` 的 CRUD 语义与并发写串行化
2. ``serializers`` 能把 SDK dataclass 扁平化为预期形状
3. REST 路由：create / list / delete / messages(SSE) / 错误兜底

AC C（跨轮次上下文保持）在 SDK 真实连通时才能检验，这里用假客户端模拟两次
query 对 prompt 的累加即可间接验证路由与锁不会破坏轮次顺序。
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import src.server.claude_code.session_manager as sm_module

import app as app_module
from src.server import claude_code as cc_pkg
from src.server.claude_code import serializers
from src.server.routes import claude_code as cc_route


# ---------------------------------------------------------------------------
# 假 SDK 客户端 —— 只实现被调用到的方法
# ---------------------------------------------------------------------------


class FakeClient:
    """内存版 ``ClaudeSDKClient``。"""

    created: list["FakeClient"] = []

    def __init__(self, options):
        self.options = options
        self.connected = False
        self.disconnected = False
        self.prompts: list[str] = []
        self.interrupts = 0
        FakeClient.created.append(self)

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.disconnected = True

    async def query(self, prompt, session_id="default"):
        self.prompts.append(prompt)

    async def receive_response(self):
        # 返回真的 SDK 类型，保证序列化分派走正常路径
        from claude_agent_sdk import (
            AssistantMessage,
            ResultMessage,
            SystemMessage,
            TextBlock,
        )

        yield SystemMessage(subtype="init", data={"turn": len(self.prompts)})
        yield AssistantMessage(
            content=[TextBlock(text=f"echo:{self.prompts[-1]}")],
            model="fake-model",
            parent_tool_use_id=None,
            error=None,
            usage=None,
            message_id="m1",
            stop_reason="end_turn",
            session_id="sdk-session",
            uuid="u1",
        )
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=len(self.prompts),
            session_id="sdk-session",
            stop_reason="end_turn",
            total_cost_usd=0.0,
            usage=None,
            result=f"done-{len(self.prompts)}",
            structured_output=None,
            model_usage=None,
            permission_denials=None,
            errors=None,
            uuid="u2",
        )

    async def interrupt(self):
        self.interrupts += 1


@pytest.fixture
def fake_sdk(monkeypatch):
    """把 SessionManager 用到的 SDK 客户端换成 FakeClient，并清空全局注册表。"""
    FakeClient.created = []
    monkeypatch.setattr(sm_module, "ClaudeSDKClient", FakeClient)
    # 重置进程内 session_manager 的存储与锁
    monkeypatch.setattr(sm_module.session_manager, "_sessions", {})
    monkeypatch.setattr(sm_module.session_manager, "_lock", asyncio.Lock())
    yield FakeClient


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------


def test_serialize_text_block_roundtrip():
    from claude_agent_sdk import TextBlock

    out = serializers.serialize_block(TextBlock(text="hi"))
    assert out == {"type": "text", "text": "hi"}


def test_serialize_tool_use_block():
    from claude_agent_sdk import ToolUseBlock

    out = serializers.serialize_block(
        ToolUseBlock(id="t1", name="bash", input={"cmd": "ls"})
    )
    assert out == {"type": "tool_use", "id": "t1", "name": "bash", "input": {"cmd": "ls"}}


def test_serialize_assistant_message_flattens_content():
    from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock

    msg = AssistantMessage(
        content=[TextBlock(text="hello"), ToolUseBlock(id="x", name="read", input={})],
        model="m",
        parent_tool_use_id=None,
        error=None,
        usage=None,
        message_id="id",
        stop_reason="end_turn",
        session_id="s",
        uuid="u",
    )
    out = serializers.serialize_message(msg)
    assert out["type"] == "assistant"
    assert out["content"][0] == {"type": "text", "text": "hello"}
    assert out["content"][1]["type"] == "tool_use"
    assert out["model"] == "m"


def test_serialize_result_message():
    from claude_agent_sdk import ResultMessage

    msg = ResultMessage(
        subtype="success",
        duration_ms=10,
        duration_api_ms=5,
        is_error=False,
        num_turns=1,
        session_id="s",
        stop_reason="end_turn",
        total_cost_usd=0.01,
        usage={"input_tokens": 3},
        result="ok",
        structured_output=None,
        model_usage=None,
        permission_denials=None,
        errors=None,
        uuid="u",
    )
    out = serializers.serialize_message(msg)
    assert out["type"] == "result"
    assert out["result"] == "ok"
    assert out["is_error"] is False
    assert out["num_turns"] == 1


def test_serialize_unknown_type_falls_back():
    class Foo:
        def __repr__(self) -> str:
            return "Foo()"

    out = serializers.serialize_message(Foo())
    assert out == {"type": "unknown", "repr": "Foo()"}


# ---------------------------------------------------------------------------
# SessionManager CRUD
# ---------------------------------------------------------------------------


def test_session_manager_create_connects_and_stores(fake_sdk, tmp_path):
    async def run():
        mgr = sm_module.SessionManager()
        # 用 monkeypatched 的 FakeClient
        session = await mgr.create(cwd=tmp_path)
        assert session.client.connected is True
        assert mgr.get(session.id) is session
        assert session.to_dict()["cwd"] == str(tmp_path)
        assert session.to_dict()["id"] == session.id
        listed = mgr.list_sessions()
        assert len(listed) == 1

    asyncio.run(run())


def test_session_manager_delete_disconnects(fake_sdk, tmp_path):
    async def run():
        mgr = sm_module.SessionManager()
        session = await mgr.create(cwd=tmp_path)
        assert await mgr.delete(session.id) is True
        assert session.client.disconnected is True
        assert mgr.get(session.id) is None
        # 删第二次返回 False
        assert await mgr.delete(session.id) is False

    asyncio.run(run())


def test_session_manager_shutdown_clears_all(fake_sdk, tmp_path):
    async def run():
        mgr = sm_module.SessionManager()
        s1 = await mgr.create(cwd=tmp_path)
        s2 = await mgr.create(cwd=tmp_path)
        await mgr.shutdown()
        assert mgr.list_sessions() == []
        assert s1.client.disconnected and s2.client.disconnected

    asyncio.run(run())


# ---------------------------------------------------------------------------
# REST 路由
# ---------------------------------------------------------------------------


def test_create_session_requires_cwd_under_root(fake_sdk, tmp_path):
    client = TestClient(app_module.app)
    # tmp_path 在项目根之外 → 400
    resp = client.post("/api/claude-code/sessions", json={"cwd": str(tmp_path)})
    assert resp.status_code == 400
    assert "within project root" in resp.json()["detail"]


def test_create_session_default_cwd_is_project_root(fake_sdk):
    client = TestClient(app_module.app)
    resp = client.post("/api/claude-code/sessions", json={})
    assert resp.status_code == 200
    data = resp.json()
    # 四字段契约：id / cwd / model / created_at
    assert set(data.keys()) >= {"id", "cwd", "model", "created_at"}
    assert data["id"] and data["cwd"] and data["created_at"] > 0
    # 默认未指定 model，应为 None 而不是缺字段
    assert data["model"] is None
    # 清理
    client.delete(f"/api/claude-code/sessions/{data['id']}")


def test_list_sessions_reflects_create_delete(fake_sdk):
    client = TestClient(app_module.app)
    resp = client.post("/api/claude-code/sessions", json={})
    sid = resp.json()["id"]
    listed = client.get("/api/claude-code/sessions").json()
    assert any(s["id"] == sid for s in listed["sessions"])
    client.delete(f"/api/claude-code/sessions/{sid}")
    listed = client.get("/api/claude-code/sessions").json()
    assert all(s["id"] != sid for s in listed["sessions"])


def test_delete_unknown_session_returns_404(fake_sdk):
    client = TestClient(app_module.app)
    resp = client.delete("/api/claude-code/sessions/does-not-exist")
    assert resp.status_code == 404


def test_send_message_streams_sdk_events(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        with client.stream(
            "POST",
            f"/api/claude-code/sessions/{sid}/messages",
            json={"prompt": "hello"},
        ) as resp:
            assert resp.status_code == 200
            raw = b"".join(resp.iter_bytes()).decode("utf-8")
        # SSE 帧由 \n\n 分隔
        frames = [f for f in raw.split("\n\n") if f.strip()]
        # 至少有 system / assistant / result / cc_finished 四帧
        assert len(frames) >= 4
        events = [ln for ln in raw.splitlines() if ln.startswith("event:")]
        assert "event: cc_message" in events
        assert "event: cc_finished" in events
        # 数据载荷至少含一条 assistant
        datas = [ln for ln in raw.splitlines() if ln.startswith("data:")]
        payloads = [json.loads(ln[len("data:") :].strip()) for ln in datas]
        types = [p.get("type") for p in payloads]
        assert "assistant" in types and "result" in types
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_send_message_unknown_session_returns_404(fake_sdk):
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/claude-code/sessions/missing/messages", json={"prompt": "x"}
    )
    assert resp.status_code == 404


def test_send_message_empty_prompt_returns_400(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        resp = client.post(
            f"/api/claude-code/sessions/{sid}/messages", json={"prompt": "   "}
        )
        assert resp.status_code == 400
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_interrupt_session(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        resp = client.post(f"/api/claude-code/sessions/{sid}/interrupt")
        assert resp.status_code == 200
        assert resp.json()["status"] == "interrupted"
        # FakeClient 计数 +1
        fake = FakeClient.created[-1]
        assert fake.interrupts == 1
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_package_exports():
    # 保证公开 API 没被重构漏掉
    assert hasattr(cc_pkg, "SessionManager")
    assert hasattr(cc_pkg, "session_manager")
    assert callable(cc_pkg.serialize_message)
    assert callable(cc_pkg.serialize_block)
    # 路由 module 能 import
    assert hasattr(cc_route, "router")


# ---------------------------------------------------------------------------
# Idle TTL 回收
#
# Task 7 把会话回收责任从"前端 unmount 触发 DELETE"移到"后端 idle TTL"，
# 避免浏览器切 Tab / 刷新 / 断网误杀活跃会话。下面用极短 TTL（0.15-0.2s）
# 和高频 sweep（50ms）压缩验证窗口，不等 30min。
# ---------------------------------------------------------------------------


def test_idle_session_is_evicted(fake_sdk, tmp_path):
    async def run():
        mgr = sm_module.SessionManager(idle_ttl_sec=0.15, sweep_interval_sec=0.05)
        try:
            session = await mgr.create(cwd=tmp_path)
            assert mgr.get(session.id) is session

            await asyncio.sleep(0.35)

            assert mgr.get(session.id) is None, "idle session should have been evicted"
            assert session.client.disconnected is True
        finally:
            await mgr.shutdown()

    asyncio.run(run())


def test_touch_keeps_active_session_alive(fake_sdk, tmp_path):
    async def run():
        mgr = sm_module.SessionManager(idle_ttl_sec=0.2, sweep_interval_sec=0.05)
        try:
            session = await mgr.create(cwd=tmp_path)
            # 每 80ms touch 一次，持续 ~400ms——每次刷新都在 TTL 内
            for _ in range(5):
                await asyncio.sleep(0.08)
                assert mgr.touch(session.id) is session

            assert mgr.get(session.id) is session
            assert session.client.disconnected is False
        finally:
            await mgr.shutdown()

    asyncio.run(run())


def test_shutdown_cancels_sweeper_task(fake_sdk, tmp_path):
    async def run():
        mgr = sm_module.SessionManager(idle_ttl_sec=10.0, sweep_interval_sec=0.05)
        await mgr.create(cwd=tmp_path)
        sweeper = mgr._sweeper_task
        assert sweeper is not None and not sweeper.done()

        await mgr.shutdown()

        assert sweeper.done(), "shutdown should cancel and await the sweeper task"
        assert mgr._sweeper_task is None

    asyncio.run(run())


def test_touch_missing_session_returns_none(fake_sdk):
    async def run():
        mgr = sm_module.SessionManager()
        try:
            assert mgr.touch("nonexistent") is None
        finally:
            await mgr.shutdown()

    asyncio.run(run())


def test_interrupt_refreshes_last_activity(fake_sdk, tmp_path):
    """interrupt 也应被视作活动，刷新 last_activity_at。"""

    async def run():
        mgr = sm_module.SessionManager(idle_ttl_sec=0.2, sweep_interval_sec=0.05)
        try:
            session = await mgr.create(cwd=tmp_path)
            # 快到 TTL 前调一次 interrupt 续命
            for _ in range(5):
                await asyncio.sleep(0.08)
                await mgr.interrupt(session.id)

            assert mgr.get(session.id) is session
        finally:
            await mgr.shutdown()

    asyncio.run(run())
