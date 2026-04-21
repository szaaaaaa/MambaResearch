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
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

logger = logging.getLogger(__name__)


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
    created_at : float
        创建 Unix 时间戳。
    last_activity_at : float
        最近一次活动（send_message / interrupt）时间戳，驱动 idle TTL 回收。
    client : ClaudeSDKClient
        已 ``connect`` 的 SDK 客户端。
    lock : asyncio.Lock
        会话级互斥锁，保证 query/receive_response 串行。
    """

    id: str
    cwd: str
    model: str | None
    created_at: float
    last_activity_at: float
    client: ClaudeSDKClient
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "cwd": self.cwd,
            "model": self.model,
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
        options_overrides: dict[str, Any] | None = None,
    ) -> ClaudeSession:
        """新建并 ``connect`` 一个 SDK 会话。

        Parameters
        ----------
        cwd : str or Path
            子进程工作目录，必须存在且由调用方校验合法性。
        model : str or None
            可选模型覆盖。
        options_overrides : dict or None
            透传给 ``ClaudeAgentOptions`` 的额外字段（未来支持 system_prompt、mcp_servers 等）。
        """
        options_kwargs: dict[str, Any] = {"cwd": str(cwd)}
        if model:
            options_kwargs["model"] = model
        if options_overrides:
            options_kwargs.update(options_overrides)

        options = ClaudeAgentOptions(**options_kwargs)
        client = ClaudeSDKClient(options=options)
        await client.connect()

        now = time.time()
        session = ClaudeSession(
            id=uuid.uuid4().hex,
            cwd=str(cwd),
            model=model,
            created_at=now,
            last_activity_at=now,
            client=client,
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
            try:
                await session.client.disconnect()
            except Exception:
                logger.exception("disconnect failed for session %s during shutdown", session.id)


session_manager = SessionManager()
