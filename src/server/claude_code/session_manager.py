"""Claude Code SDK 会话注册表。

``ClaudeSession`` 包装一个 ``ClaudeSDKClient``，每个会话常驻一条 CLI 子进程，跨多次 HTTP
请求保持上下文。``SessionManager`` 是进程内的会话注册表，提供 CRUD 并在删除时按序调用
``disconnect`` 清理。

并发注意事项：
- ``_sessions`` 的增删由 ``asyncio.Lock`` 守护，避免并发 create/delete 撞击。
- 单个会话内部另有一个 ``asyncio.Lock``（``ClaudeSession.lock``），路由层在调 ``query`` +
  迭代 ``receive_response`` 时必须加锁，防止同一会话并发写入 stdin 造成帧错乱。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
)

logger = logging.getLogger(__name__)

# 与 SDK 字面量一致，禁止前端传入 "strict" 这种非 SDK 合法值
VALID_PERMISSION_MODES: frozenset[str] = frozenset(
    {"default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"}
)
# 仅在 "default" 模式下注入 can_use_tool 桥触发 Modal；其余模式沿用 SDK 原生语义
_INTERACTIVE_PERMISSION_MODES: frozenset[str] = frozenset({"default"})

# SSE 发射器签名：(event_name, payload_dict) -> None
SseEmitter = Callable[[str, dict[str, Any]], None]


@dataclass
class PermissionState:
    """单会话级 HITL 权限状态。

    - ``allowed_always`` 缓存本会话内用户点过"允许（本会话）"的工具名
    - ``pending_requests`` 由 bridge 填充、由 REST 决策端点解锁
    - ``current_sse_emitter`` 每一轮 send_message 进入时绑定到该轮 SSE 队列，
      轮结束后路由层负责清空——bridge 通过它把权限请求帧推到当前活跃 SSE 流
    """

    allowed_always: set[str] = field(default_factory=set)
    pending_requests: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    current_sse_emitter: SseEmitter | None = None


def _build_permission_bridge(
    session_id: str, state: PermissionState
) -> Callable[..., Any]:
    """构造 SDK ``can_use_tool`` 异步桥。

    命中 ``allowed_always`` → 直接 allow；否则生成 ``request_id``，通过
    ``current_sse_emitter`` 推 ``cc_permission_request`` 帧，等待 Future
    被 REST 决策端点 ``set_result``，将结果映射回 SDK PermissionResult。
    """

    async def bridge(tool_name: str, tool_input: dict[str, Any], _context: Any):
        if tool_name in state.allowed_always:
            return PermissionResultAllow()
        emitter = state.current_sse_emitter
        if emitter is None:
            # 理论不会发生——query 必须在 current_sse_emitter 绑定后才跑
            return PermissionResultDeny(
                message="no active SSE channel for permission request"
            )
        request_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        state.pending_requests[request_id] = fut
        try:
            emitter(
                "cc_permission_request",
                {
                    "request_id": request_id,
                    "session_id": session_id,
                    "tool_name": tool_name,
                    "input": tool_input,
                },
            )
            result = await fut
        finally:
            state.pending_requests.pop(request_id, None)

        decision = result.get("decision") if isinstance(result, dict) else None
        message = result.get("message") if isinstance(result, dict) else None
        if decision == "allow":
            return PermissionResultAllow()
        if decision == "allow_session":
            state.allowed_always.add(tool_name)
            return PermissionResultAllow()
        return PermissionResultDeny(message=str(message or "user denied"))

    return bridge


@dataclass
class ClaudeSession:
    """单条 Claude Code 会话。

    Attributes
    ----------
    id : str
        会话 ID（前端引用凭据，由后端生成的 UUID，而非 SDK 侧 session_id）。
    cwd : str
        子进程工作目录。
    model : str or None
        指定模型；None 表示使用 CLI 默认。
    permission_mode : str
        SDK ``PermissionMode`` 字面量之一。仅 ``"default"`` 时桥挂钩触发前端 Modal，
        其余模式沿用 SDK 原生语义（acceptEdits 自动放行编辑工具等）。
    created_at : float
        创建 Unix 时间戳。
    last_activity_at : float
        最近一次活动（send_message / interrupt）时间戳，驱动 idle TTL 回收。
    client : ClaudeSDKClient
        已 ``connect`` 的 SDK 客户端。
    lock : asyncio.Lock
        会话级互斥锁，保证 query/receive_response 串行。
    permission_state : PermissionState
        HITL 权限请求状态（allowed_always 缓存、pending_requests Future 表、
        当前轮 SSE 发射器）。
    """

    id: str
    cwd: str
    model: str | None
    permission_mode: str
    created_at: float
    last_activity_at: float
    client: ClaudeSDKClient
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    permission_state: PermissionState = field(default_factory=PermissionState)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "cwd": self.cwd,
            "model": self.model,
            "permission_mode": self.permission_mode,
            "created_at": self.created_at,
        }


DEFAULT_IDLE_TTL_SEC = 3600.0  # 60 分钟无活动自动回收 SDK client
DEFAULT_SWEEP_INTERVAL_SEC = 60.0


class SessionManager:
    """进程内 Claude Code 会话注册表。

    Idle TTL 回收：
    ``last_activity_at`` 由 ``touch`` 在每次 ``send_message`` / ``interrupt`` 时刷新；
    后台 sweeper 每 ``sweep_interval_sec`` 秒扫一次，超过 ``idle_ttl_sec`` 未活动的
    会话会被调 ``disconnect`` 并从注册表移除。前端 Tab 切换/浏览器刷新不再需要触发
    ``DELETE`` 端点，避免误杀活跃会话。
    """

    def __init__(
        self,
        *,
        idle_ttl_sec: float = DEFAULT_IDLE_TTL_SEC,
        sweep_interval_sec: float = DEFAULT_SWEEP_INTERVAL_SEC,
    ) -> None:
        self._sessions: dict[str, ClaudeSession] = {}
        self._lock = asyncio.Lock()
        self.idle_ttl_sec = idle_ttl_sec
        self.sweep_interval_sec = sweep_interval_sec
        self._sweeper_task: asyncio.Task[None] | None = None

    async def create(
        self,
        cwd: str | Path,
        *,
        model: str | None = None,
        permission_mode: str = "default",
        options_overrides: dict[str, Any] | None = None,
    ) -> ClaudeSession:
        """新建并 ``connect`` 一个 SDK 会话。

        Parameters
        ----------
        cwd : str or Path
            子进程工作目录，必须存在且由调用方校验合法性。
        model : str or None
            可选模型覆盖。
        permission_mode : str
            SDK PermissionMode 字面量，默认 ``"default"``（每次弹 Modal）。传入
            非法值会 raise ValueError。仅 ``"default"`` 模式注入 can_use_tool 桥。
        options_overrides : dict or None
            透传给 ``ClaudeAgentOptions`` 的额外字段（未来支持 system_prompt、mcp_servers 等）。
        """
        if permission_mode not in VALID_PERMISSION_MODES:
            raise ValueError(
                f"invalid permission_mode: {permission_mode!r} "
                f"(must be one of {sorted(VALID_PERMISSION_MODES)})"
            )

        session_id = uuid.uuid4().hex
        permission_state = PermissionState()

        options_kwargs: dict[str, Any] = {
            "cwd": str(cwd),
            "permission_mode": permission_mode,
        }
        if model:
            options_kwargs["model"] = model
        if permission_mode in _INTERACTIVE_PERMISSION_MODES:
            options_kwargs["can_use_tool"] = _build_permission_bridge(
                session_id, permission_state
            )
        if options_overrides:
            options_kwargs.update(options_overrides)

        options = ClaudeAgentOptions(**options_kwargs)
        client = ClaudeSDKClient(options=options)
        await client.connect()

        now = time.time()
        session = ClaudeSession(
            id=session_id,
            cwd=str(cwd),
            model=model,
            permission_mode=permission_mode,
            created_at=now,
            last_activity_at=now,
            client=client,
            permission_state=permission_state,
        )
        async with self._lock:
            self._sessions[session.id] = session
        self._ensure_sweeper()
        return session

    def get(self, session_id: str) -> ClaudeSession | None:
        return self._sessions.get(session_id)

    def touch(self, session_id: str) -> ClaudeSession | None:
        """原子刷新活跃时间戳并返回会话。

        将"查找"和"打点"合成单次 sync 操作——无 await 点，相对 sweeper 的
        ``async with self._lock:`` 临界段天然串行：要么先于 sweeper 跑完刷新了
        时间戳（sweeper 看到新值不 evict），要么在 sweeper evict 之后跑（dict
        已 pop，返回 ``None``）。调用方凭返回值一次拿到 session，不需要再调
        ``get`` 从而规避 get/touch 之间被抢占的竞争。
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None
        session.last_activity_at = time.time()
        return session

    async def delete(self, session_id: str) -> bool:
        """断开并移除会话。返回是否实际删除了会话。"""
        async with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        # 先解锁所有悬挂的权限 Future，避免 SDK 协程 await 死在那
        _cancel_pending_permissions(session)
        try:
            await session.client.disconnect()
        except Exception:
            # 已崩溃/已断开的会话 disconnect 可能再次抛错——注册表必须清理成功，
            # 不 raise 让路由能返回成功，但留日志便于事后排查
            logger.exception("disconnect failed for session %s", session.id)
        return True

    async def interrupt(self, session_id: str) -> bool:
        """打断指定会话当前推理。返回会话是否存在；SDK 抛错向外传播由路由层转 5xx。"""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session.last_activity_at = time.time()
        await session.client.interrupt()
        return True

    def list_sessions(self) -> list[ClaudeSession]:
        return list(self._sessions.values())

    def _ensure_sweeper(self) -> None:
        """首次注册会话时 lazy 启动 sweeper；已运行则 no-op。"""
        if self._sweeper_task is not None and not self._sweeper_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 没有运行中的 event loop（比如同步测试场景）——放弃启动
            return
        self._sweeper_task = loop.create_task(self._sweep_loop(), name="claude-code-sweeper")

    async def _sweep_loop(self) -> None:
        """周期扫描 idle 会话并 evict。异常只记录不冒泡，避免 loop 挂死。"""
        while True:
            try:
                await asyncio.sleep(self.sweep_interval_sec)
            except asyncio.CancelledError:
                raise
            try:
                await self._evict_idle()
            except Exception:
                logger.exception("idle sweeper iteration failed")

    async def _evict_idle(self) -> None:
        now = time.time()
        ttl = self.idle_ttl_sec
        async with self._lock:
            idle_ids = [
                sid
                for sid, sess in self._sessions.items()
                if now - sess.last_activity_at > ttl
            ]
            victims = [self._sessions.pop(sid) for sid in idle_ids]
        for session in victims:
            logger.info("session %s evicted by idle ttl (>%.0fs)", session.id, ttl)
            _cancel_pending_permissions(session)
            try:
                await session.client.disconnect()
            except Exception:
                logger.exception("disconnect failed during idle eviction for %s", session.id)

    async def shutdown(self) -> None:
        """进程关停时取消 sweeper 并统一断开所有会话。"""
        sweeper = self._sweeper_task
        self._sweeper_task = None
        if sweeper is not None and not sweeper.done():
            sweeper.cancel()
            try:
                await sweeper
            except (asyncio.CancelledError, Exception):
                pass
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            _cancel_pending_permissions(session)
            try:
                await session.client.disconnect()
            except Exception:
                logger.exception("disconnect failed for session %s during shutdown", session.id)


def _cancel_pending_permissions(session: ClaudeSession) -> None:
    """会话关停前把所有悬挂的权限 Future 置为 deny，避免 SDK 侧死等。"""
    state = session.permission_state
    state.current_sse_emitter = None
    if not state.pending_requests:
        return
    pending = list(state.pending_requests.values())
    state.pending_requests.clear()
    for fut in pending:
        if not fut.done():
            fut.set_result({"decision": "deny", "message": "session closed"})


session_manager = SessionManager()
