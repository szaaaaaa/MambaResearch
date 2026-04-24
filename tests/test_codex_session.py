"""Codex session manager 测试（Task 5bc）。

与 ``test_claude_code_session.py`` 对偶——真实 ``codex app-server`` 子进程需要
ChatGPT OAuth 凭据 + 网络，CI 与 /ship 前的单测都不可靠跑它。本测试通过 fake
``AppServerClient`` 注入到 ``CodexSessionManager``，只验证：

1. ``FakeAppServerClient`` 运行时符合 ``AppServerClient`` Protocol 契约
2. ``CodexSessionManager`` 的 CRUD 语义（create / delete）+ sandbox_mode 校验
   + auth pre-flight
3. ``send_message`` async generator 正确 yield 脚本化的 notifications
4. ``PermissionState`` / ``_build_permission_bridge`` HITL 状态机行为
5. Idle TTL sweeper 的 eviction 路径

同步测试函数内嵌 ``async def run()`` + ``asyncio.run(run())``——与仓库既有测试
风格一致（项目未装 pytest-asyncio）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from src.server.codex.app_server_client import AppServerClient
from src.server.codex.session_manager import (
    DEFAULT_CODEX_MODEL,
    CodexAuthError,
    CodexSession,
    CodexSessionManager,
    PermissionState,
    _build_permission_bridge,
)


# ---------------------------------------------------------------------------
# FakeAppServerClient —— 内存版 client，替代真实 codex subprocess
# ---------------------------------------------------------------------------


class FakeAppServerClient:
    """Protocol 兼容的内存 client——只实现 session manager 调到的方法。

    行为：
    - ``connect`` / ``disconnect``：切换 ``_connected`` 状态并计数
    - ``send_message``：按 ``scripted_messages`` 顺序 yield；每次调用累加
      ``sent_messages`` 便于断言
    - ``interrupt`` / ``is_connected``：桩实现
    """

    def __init__(
        self,
        *,
        cwd: str,
        model: str = "gpt-5.5",
        sandbox_mode: str = "read-only",
        scripted_messages: list[dict[str, Any]] | None = None,
    ) -> None:
        self.cwd = cwd
        self.model = model
        self.sandbox_mode = sandbox_mode
        self.scripted_messages = list(scripted_messages or [])
        self._connected = False
        self.connect_count = 0
        self.disconnect_count = 0
        self.interrupt_count = 0
        self.sent_messages: list[str] = []

    async def connect(self) -> None:
        self._connected = True
        self.connect_count += 1

    async def disconnect(self) -> None:
        self._connected = False
        self.disconnect_count += 1

    async def send_message(self, text: str) -> AsyncIterator[dict[str, Any]]:
        self.sent_messages.append(text)
        for msg in self.scripted_messages:
            yield msg

    async def interrupt(self) -> None:
        self.interrupt_count += 1

    async def is_connected(self) -> bool:
        return self._connected


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_codex_home(tmp_path: Path) -> Path:
    """造一个最小 ``~/.codex``——含非空 ``auth.json`` 通过 pre-flight。"""
    home = tmp_path / "codex_home"
    home.mkdir()
    (home / "auth.json").write_text('{"token": "fake"}', encoding="utf-8")
    return home


@pytest.fixture
def fake_factory():
    """返回一个 factory + 它 spawn 出来的 clients 列表，供断言使用。"""
    spawned: list[FakeAppServerClient] = []

    async def factory(
        *,
        session_id: str,
        cwd: str,
        model: str,
        sandbox_mode: str,
        permission_state: PermissionState,
    ) -> FakeAppServerClient:
        client = FakeAppServerClient(
            cwd=cwd, model=model, sandbox_mode=sandbox_mode
        )
        await client.connect()
        spawned.append(client)
        return client

    factory.spawned = spawned  # type: ignore[attr-defined]
    return factory


@pytest.fixture
def manager(fake_codex_home, fake_factory):
    """默认 TTL 不会误触 sweeper，sweep_interval 很长，测试里不启动 sweeper。"""
    return CodexSessionManager(
        idle_ttl_sec=3600.0,
        sweep_interval_sec=3600.0,
        client_factory=fake_factory,
        codex_home=fake_codex_home,
    )


# ---------------------------------------------------------------------------
# Protocol 契约
# ---------------------------------------------------------------------------


def test_fake_client_satisfies_app_server_protocol():
    """FakeAppServerClient 必须通过 ``@runtime_checkable`` isinstance 检查。"""
    fake = FakeAppServerClient(cwd="/tmp")
    assert isinstance(fake, AppServerClient)


# ---------------------------------------------------------------------------
# CodexSessionManager.create
# ---------------------------------------------------------------------------


def test_create_returns_session_with_expected_fields(manager, fake_factory):
    async def run():
        session = await manager.create(
            cwd="/some/path", sandbox_mode="workspace-write"
        )
        assert isinstance(session, CodexSession)
        assert session.cwd == "/some/path"
        assert session.model == DEFAULT_CODEX_MODEL == "gpt-5.5"
        assert session.sandbox_mode == "workspace-write"
        assert session.created_at > 0
        assert session.last_activity_at == session.created_at
        assert isinstance(session.id, str) and len(session.id) == 32  # uuid hex
        # client 已 connected 且为 factory spawn 的同一个
        assert await session.client.is_connected()
        assert session.client is fake_factory.spawned[0]
        assert fake_factory.spawned[0].connect_count == 1
        # to_dict 带 provider 字段供路由分派
        d = session.to_dict()
        assert d["provider"] == "codex"
        assert d["sandbox_mode"] == "workspace-write"

    asyncio.run(run())


def test_create_registers_session_in_manager(manager):
    async def run():
        session = await manager.create(cwd="/x")
        assert manager.get(session.id) is session
        assert manager.list_sessions() == [session]

    asyncio.run(run())


def test_create_invalid_sandbox_mode_raises(manager):
    async def run():
        with pytest.raises(ValueError, match="sandbox_mode"):
            await manager.create(cwd="/x", sandbox_mode="extreme-access")

    asyncio.run(run())


def test_create_missing_auth_json_raises(fake_factory, tmp_path):
    """``~/.codex/auth.json`` 不存在 → CodexAuthError。"""
    empty = tmp_path / "no_auth"
    empty.mkdir()  # 目录存在但没 auth.json
    m = CodexSessionManager(
        client_factory=fake_factory, codex_home=empty
    )

    async def run():
        with pytest.raises(CodexAuthError, match="not found"):
            await m.create(cwd="/x")

    asyncio.run(run())


def test_create_empty_auth_json_raises(fake_factory, tmp_path):
    """``auth.json`` 存在但空内容 → CodexAuthError。"""
    home = tmp_path / "empty_auth"
    home.mkdir()
    (home / "auth.json").write_text("   \n", encoding="utf-8")
    m = CodexSessionManager(client_factory=fake_factory, codex_home=home)

    async def run():
        with pytest.raises(CodexAuthError, match="empty"):
            await m.create(cwd="/x")

    asyncio.run(run())


# ---------------------------------------------------------------------------
# CodexSessionManager.delete
# ---------------------------------------------------------------------------


def test_delete_disconnects_and_removes_session(manager):
    async def run():
        session = await manager.create(cwd="/x")
        sid = session.id
        client = session.client
        deleted = await manager.delete(sid)
        assert deleted is True
        assert manager.get(sid) is None
        assert client.disconnect_count == 1
        assert not await client.is_connected()

    asyncio.run(run())


def test_delete_unknown_session_returns_false(manager):
    async def run():
        assert (await manager.delete("does-not-exist")) is False

    asyncio.run(run())


def test_delete_twice_returns_false_second_time(manager):
    async def run():
        session = await manager.create(cwd="/x")
        assert (await manager.delete(session.id)) is True
        assert (await manager.delete(session.id)) is False

    asyncio.run(run())


# ---------------------------------------------------------------------------
# send_message — 通过 client.send_message 验证回包 + 状态机转换
# ---------------------------------------------------------------------------


def test_send_message_yields_scripted_notifications_in_order():
    async def run():
        scripted = [
            {
                "jsonrpc": "2.0",
                "method": "turn/started",
                "params": {"turnId": "t1", "threadId": "th1"},
            },
            {
                "jsonrpc": "2.0",
                "method": "item/agentMessage/delta",
                "params": {"delta": "Hel", "itemId": "m1"},
            },
            {
                "jsonrpc": "2.0",
                "method": "item/agentMessage/delta",
                "params": {"delta": "lo!", "itemId": "m1"},
            },
            {
                "jsonrpc": "2.0",
                "method": "turn/completed",
                "params": {"turnId": "t1"},
            },
        ]
        fake = FakeAppServerClient(
            cwd="/x", model="gpt-5.5", sandbox_mode="read-only",
            scripted_messages=scripted,
        )
        await fake.connect()
        collected: list[dict[str, Any]] = []
        async for msg in fake.send_message("Hi"):
            collected.append(msg)
        # 按顺序 yield 全部 4 帧，每帧结构保留 method + params
        assert len(collected) == 4
        assert [m["method"] for m in collected] == [
            "turn/started",
            "item/agentMessage/delta",
            "item/agentMessage/delta",
            "turn/completed",
        ]
        assert collected[1]["params"]["delta"] == "Hel"
        assert collected[3]["params"]["turnId"] == "t1"
        # sent_messages 记录了这次调用
        assert fake.sent_messages == ["Hi"]

    asyncio.run(run())


def test_send_message_records_each_call(manager):
    async def run():
        session = await manager.create(cwd="/x")
        fake = session.client
        assert isinstance(fake, FakeAppServerClient)
        # 每次 iterate 都触发 scripted_messages（这里默认空）
        collected = [m async for m in fake.send_message("first")]
        assert collected == []
        assert fake.sent_messages == ["first"]
        # 第二次调用会追加
        _ = [m async for m in fake.send_message("second")]
        assert fake.sent_messages == ["first", "second"]

    asyncio.run(run())


# ---------------------------------------------------------------------------
# PermissionState + _build_permission_bridge
# ---------------------------------------------------------------------------


def test_permission_state_defaults():
    state = PermissionState()
    assert state.allowed_always == set()
    assert state.pending_requests == {}
    assert state.current_sse_emitter is None


def test_bridge_returns_allow_for_cached_action():
    """``allowed_always`` 命中直接放行，不触发 SSE 推送。"""

    async def run():
        state = PermissionState()
        state.allowed_always.add("execCommandApproval:ls -la")
        bridge = _build_permission_bridge("session-1", state)
        result = await bridge("execCommandApproval:ls -la", {"command": "ls -la"})
        assert result == {"decision": "allow", "message": None}
        # pending_requests 保持为空——没走 SSE 等待路径
        assert state.pending_requests == {}

    asyncio.run(run())


def test_bridge_returns_deny_when_no_sse_emitter():
    """未绑定 ``current_sse_emitter`` 时 bridge 走 deny fallback，避免死等。"""

    async def run():
        state = PermissionState()
        bridge = _build_permission_bridge("session-1", state)
        result = await bridge("execCommandApproval:rm", {"command": "rm"})
        assert result["decision"] == "deny"
        assert "no active SSE channel" in str(result["message"])

    asyncio.run(run())


def test_bridge_user_allow_session_caches_for_future():
    """模拟前端返回 ``allow_session``——加入 allowed_always，下次同 key 自动放行。"""

    async def run():
        state = PermissionState()
        # 模拟已绑定 SSE 发射器——这里不需要真发，只需要存在
        pushed: list[tuple[str, dict[str, Any]]] = []

        def emitter(event_name: str, payload: dict[str, Any]) -> None:
            pushed.append((event_name, payload))

        state.current_sse_emitter = emitter
        bridge = _build_permission_bridge("session-1", state)

        async def decide_later():
            await asyncio.sleep(0.01)
            # 前端"选允许本会话"——通过 pending_requests Future set_result
            assert len(state.pending_requests) == 1
            (request_id, fut), = state.pending_requests.items()
            fut.set_result({"decision": "allow_session", "message": None})

        decider = asyncio.create_task(decide_later())
        result = await bridge("execCommandApproval:ls", {"command": "ls"})
        await decider
        assert result == {"decision": "allow", "message": None}
        # 下次同 key 直接命中缓存
        assert "execCommandApproval:ls" in state.allowed_always

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Idle TTL sweeper —— _evict_idle 直接调用（不启动 sweeper loop）
# ---------------------------------------------------------------------------


def test_evict_idle_removes_stale_session(fake_codex_home, fake_factory):
    """``last_activity_at`` 过老的 session 被 _evict_idle 清掉 + 客户端 disconnect。"""
    m = CodexSessionManager(
        idle_ttl_sec=0.5,  # 500ms TTL
        sweep_interval_sec=3600.0,  # 关闭 sweeper，手动触发 evict
        client_factory=fake_factory,
        codex_home=fake_codex_home,
    )

    async def run():
        session = await m.create(cwd="/x")
        client = session.client
        # 把 activity 时间戳向前推 10 秒——模拟"很久没活动"
        session.last_activity_at -= 10.0
        await m._evict_idle()
        assert m.get(session.id) is None
        assert client.disconnect_count == 1

    asyncio.run(run())


def test_evict_idle_keeps_recent_session(fake_codex_home, fake_factory):
    """活跃 session 不会被 evict。"""
    m = CodexSessionManager(
        idle_ttl_sec=3600.0,
        sweep_interval_sec=3600.0,
        client_factory=fake_factory,
        codex_home=fake_codex_home,
    )

    async def run():
        session = await m.create(cwd="/x")
        await m._evict_idle()
        # 应 still there
        assert m.get(session.id) is session
        assert session.client.disconnect_count == 0

    asyncio.run(run())


# ---------------------------------------------------------------------------
# interrupt + touch 辅助路径
# ---------------------------------------------------------------------------


def test_interrupt_calls_client_and_touches(manager):
    async def run():
        session = await manager.create(cwd="/x")
        original_activity = session.last_activity_at
        # Windows ``time.time()`` 分辨率 ~15ms——sleep 50ms 确保 tick 过边界
        await asyncio.sleep(0.05)
        result = await manager.interrupt(session.id)
        assert result is True
        assert session.client.interrupt_count == 1
        assert session.last_activity_at > original_activity

    asyncio.run(run())


def test_interrupt_unknown_session_returns_false(manager):
    async def run():
        assert (await manager.interrupt("nope")) is False

    asyncio.run(run())


def test_touch_refreshes_activity(manager):
    async def run():
        session = await manager.create(cwd="/x")
        original = session.last_activity_at
        # Windows ``time.time()`` 分辨率 ~15ms——sleep 50ms 确保 tick 过边界
        await asyncio.sleep(0.05)
        result = manager.touch(session.id)
        assert result is session
        assert session.last_activity_at > original

    asyncio.run(run())


def test_touch_unknown_session_returns_none(manager):
    assert manager.touch("nope") is None


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------


def test_shutdown_disconnects_all(fake_codex_home, fake_factory):
    m = CodexSessionManager(
        idle_ttl_sec=3600.0,
        sweep_interval_sec=3600.0,
        client_factory=fake_factory,
        codex_home=fake_codex_home,
    )

    async def run():
        s1 = await m.create(cwd="/a")
        s2 = await m.create(cwd="/b")
        await m.shutdown()
        assert m.list_sessions() == []
        assert s1.client.disconnect_count == 1
        assert s2.client.disconnect_count == 1

    asyncio.run(run())
