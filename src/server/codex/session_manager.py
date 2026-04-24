"""Codex 会话注册表（Task 5ba）。

设计与 ``src/server/claude_code/session_manager.py`` 对偶——每个 ``CodexSession``
包装一个 ``AppServerClient``（``codex app-server`` 子进程客户端），跨多次 HTTP
请求保留上下文；``CodexSessionManager`` 做进程内 CRUD 并在删除时按序 disconnect
清理。两条并行的 provider 路径（Claude / Codex）在上层由路由按
``session.provider`` 分派。

本阶段（5ba）范围限定
---------------------
* 提供 ``create / delete / get / get_or_restore / touch / interrupt / shutdown``
  + idle TTL sweeper + ``PermissionState`` HITL 状态机
* ``_build_client`` 默认返回 ``StubAppServerClient``——真实 JSON-RPC over stdio
  实现由 5bb 取代，接口不变
* **不包括**：``send_message`` 端到端流（转发事件给 SSE）、``switch_model`` /
  ``switch_sandbox_mode`` 等运行时 mutator、``record_event`` 持久化——这些属
  5bb/5c 和后续持久化 store 的职责

OAuth 路径
~~~~~~~~~~
Codex 二进制原生读 ``~/.codex/auth.json`` 完成 ChatGPT 订阅 OAuth，Workbench
后端不中转 token。``create`` 时做一次 pre-flight：如果缺 auth.json 直接抛
``CodexAuthError``，让路由层转 4xx，早于子进程启动失败。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from src.server.codex.app_server_client import (
    AppServerClient,
    StubAppServerClient,
)

logger = logging.getLogger(__name__)

# 默认按 gpt-5.5（plan 决定：Codex 侧不做模型分档；参见
# docs/plans/2026-04-23-multi-model-subagent.md 2026-04-24 决策）
DEFAULT_CODEX_MODEL = "gpt-5.5"

# Codex sandbox_mode 合法枚举——与 codex CLI 的 sandbox 设定对齐
VALID_SANDBOX_MODES: frozenset[str] = frozenset(
    {"read-only", "workspace-write", "danger-full-access"}
)

# SSE 发射器签名：(event_name, payload_dict) -> None
SseEmitter = Callable[[str, dict[str, Any]], None]

# 默认 ~/.codex 路径——测试可通过 monkeypatch 替换
DEFAULT_CODEX_HOME = Path.home() / ".codex"


class CodexAuthError(RuntimeError):
    """``~/.codex/auth.json`` 缺失或格式非法时抛出。

    不做 token 校验（token 过期由 codex 自己处理）——只做"文件存在 + 可读
    JSON"这一层 pre-flight，避免创建会话后 codex 子进程启动时才失败。
    """


@dataclass
class PermissionState:
    """单会话级 HITL 权限状态——与 Claude 侧对偶。

    Codex 的 HITL 触发点比 Claude 更粗粒度（shell 命令整条批准、文件写操作
    按 path 批准），具体行为由 5bb 的 client 实现决定。本 dataclass 只提供
    共享数据结构，不绑定具体语义。

    Attributes
    ----------
    allowed_always : set[str]
        本会话内用户点过"允许（本会话）"的 action key 缓存。key 格式由 bridge
        决定（如 ``shell:git status`` / ``file_write:/path``）。
    pending_requests : dict[str, asyncio.Future]
        由 bridge 填充、由 REST 决策端点 ``set_result`` 解锁的 Future 表。
    current_sse_emitter : SseEmitter or None
        每一轮 send_message 进入时绑定到该轮 SSE 队列，轮结束后路由层负责清空。
        bridge 通过它把权限请求帧推到当前活跃 SSE 流。
    """

    allowed_always: set[str] = field(default_factory=set)
    pending_requests: dict[str, asyncio.Future[dict[str, Any]]] = field(
        default_factory=dict
    )
    current_sse_emitter: SseEmitter | None = None


# bridge 类型——接收 action_key + payload，返回决策 dict：
#   {"decision": "allow" / "allow_session" / "deny", "message": str | None}
PermissionBridge = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def _build_permission_bridge(
    session_id: str, state: PermissionState
) -> PermissionBridge:
    """构造 HITL 权限 bridge——命中 allow_always 直接放行；否则通过 SSE 推请求
    并等 Future。

    与 Claude 侧 ``can_use_tool`` bridge 语义一致——区别仅在：

    * Claude 侧参数是 ``(tool_name, tool_input, context)`` → 返回 SDK
      ``PermissionResultAllow/Deny`` 对象
    * Codex 侧参数是 ``(action_key, payload)`` → 返回 plain dict，让
      ``app_server_client`` 侧自己把 dict 转成 JSON-RPC 应答帧

    这层间接让 session_manager 不必依赖具体协议。

    Parameters
    ----------
    session_id : str
        用于填充 SSE 帧的 session_id 字段，便于前端路由 Modal。
    state : PermissionState
        目标会话的权限状态对象，bridge 读 ``allowed_always`` + 写
        ``pending_requests``。
    """

    async def bridge(action_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action_key in state.allowed_always:
            return {"decision": "allow", "message": None}
        emitter = state.current_sse_emitter
        if emitter is None:
            # 理论不会发生：send_message 必须先绑 emitter 才进入 bridge 调用链
            return {
                "decision": "deny",
                "message": "no active SSE channel for permission request",
            }
        request_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        state.pending_requests[request_id] = fut
        try:
            emitter(
                "codex_permission_request",
                {
                    "request_id": request_id,
                    "session_id": session_id,
                    "action_key": action_key,
                    "payload": payload,
                },
            )
            result = await fut
        finally:
            state.pending_requests.pop(request_id, None)

        decision = result.get("decision") if isinstance(result, dict) else None
        message = result.get("message") if isinstance(result, dict) else None
        if decision == "allow":
            return {"decision": "allow", "message": None}
        if decision == "allow_session":
            state.allowed_always.add(action_key)
            return {"decision": "allow", "message": None}
        return {"decision": "deny", "message": str(message or "user denied")}

    return bridge


@dataclass
class CodexSession:
    """单条 Codex 会话。

    Attributes
    ----------
    id : str
        会话 ID（后端生成的 UUID，也是 app-server 侧的 sessionId）。
    cwd : str
        子进程工作目录，codex app-server 在此目录下启动。
    model : str
        模型字符串——默认 ``gpt-5.5``（plan 决定不分档）。
    sandbox_mode : str
        codex sandbox 模式，影响 app-server 允许的操作范围。必须是
        ``VALID_SANDBOX_MODES`` 之一。
    created_at : float
        创建 Unix 时间戳。
    last_activity_at : float
        最近一次活动时间戳，驱动 idle TTL 回收。
    client : AppServerClient
        已 ``connect`` 的 app-server 客户端（5ba 用 stub，5bb 换真实）。
    lock : asyncio.Lock
        会话级互斥锁——保证后续 send_message / interrupt 调用串行，防止同一
        client 并发写 stdin 造成 JSON-RPC 帧错乱。
    permission_state : PermissionState
        HITL 状态机。
    """

    id: str
    cwd: str
    model: str
    sandbox_mode: str
    created_at: float
    last_activity_at: float
    client: AppServerClient
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    permission_state: PermissionState = field(default_factory=PermissionState)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "cwd": self.cwd,
            "model": self.model,
            "sandbox_mode": self.sandbox_mode,
            "created_at": self.created_at,
            "provider": "codex",  # 路由分派的标识字段
        }


DEFAULT_IDLE_TTL_SEC = 3600.0  # 60 分钟无活动自动回收 client
DEFAULT_SWEEP_INTERVAL_SEC = 60.0


# _build_client 工厂签名——方便测试 monkeypatch 替换为 FakeClient
AppServerClientFactory = Callable[..., Awaitable[AppServerClient]]


async def _default_build_client(
    *,
    session_id: str,
    cwd: str,
    model: str,
    sandbox_mode: str,
    permission_state: PermissionState,
) -> AppServerClient:
    """5ba 默认工厂：返回 ``StubAppServerClient`` 并 ``connect``。

    5bb 会把此函数替换为真实实现——spawn ``codex app-server --listen stdio://``、
    JSON-RPC schema 校验、SSE 流适配等全部在那边落地。工厂签名保持不变。

    Parameters
    ----------
    session_id : str
        后端 UUID，同时作为 app-server sessionId 和 permission bridge 凭据。
    cwd, model, sandbox_mode : str
        透传给 client 构造器。
    permission_state : PermissionState
        5bb 的实现里会构造 bridge 注入到 client；5ba 的 stub 不需要。

    Returns
    -------
    AppServerClient
        已 ``connect`` 的客户端（stub 阶段仅标记 connected=True）。
    """
    client = StubAppServerClient(cwd=cwd, model=model, sandbox_mode=sandbox_mode)
    await client.connect()
    return client


def _check_codex_auth(codex_home: Path = DEFAULT_CODEX_HOME) -> None:
    """Pre-flight：``~/.codex/auth.json`` 必须存在且是合法 JSON。

    Codex 二进制原生读此文件做 ChatGPT 订阅 OAuth——Workbench 不做 token 中转。
    这里只校验"文件在 + 可读"最浅层，token 过期 / 刷新由 codex 自己处理。
    """
    auth_path = codex_home / "auth.json"
    if not auth_path.exists():
        raise CodexAuthError(
            f"codex OAuth credentials not found at {auth_path}. "
            "Run `codex login` first to authenticate with your ChatGPT subscription."
        )
    # 轻量校验——读到非空即可（避免空文件 / 权限问题在启动子进程时才暴露）
    try:
        content = auth_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CodexAuthError(
            f"codex auth.json unreadable at {auth_path}: {exc}"
        ) from exc
    if not content.strip():
        raise CodexAuthError(
            f"codex auth.json is empty at {auth_path}. "
            "Run `codex login` to regenerate."
        )


class CodexSessionManager:
    """进程内 Codex 会话注册表。

    Idle TTL 回收与 ``ClaudeSessionManager`` 同机制——``touch`` 刷新时间戳，
    后台 sweeper 周期清理超 TTL 会话（调 ``disconnect`` + 移除 dict 项）。
    """

    def __init__(
        self,
        *,
        idle_ttl_sec: float = DEFAULT_IDLE_TTL_SEC,
        sweep_interval_sec: float = DEFAULT_SWEEP_INTERVAL_SEC,
        client_factory: AppServerClientFactory | None = None,
        codex_home: Path = DEFAULT_CODEX_HOME,
    ) -> None:
        self._sessions: dict[str, CodexSession] = {}
        self._lock = asyncio.Lock()
        self.idle_ttl_sec = idle_ttl_sec
        self.sweep_interval_sec = sweep_interval_sec
        self._sweeper_task: asyncio.Task[None] | None = None
        # 允许测试注入自定义 factory（替换为 FakeClient 构造器）
        self._client_factory: AppServerClientFactory = (
            client_factory or _default_build_client
        )
        self._codex_home = codex_home

    async def create(
        self,
        cwd: str | Path,
        *,
        model: str = DEFAULT_CODEX_MODEL,
        sandbox_mode: str = "read-only",
    ) -> CodexSession:
        """新建并 ``connect`` 一个 app-server 会话。

        Parameters
        ----------
        cwd : str or Path
            子进程工作目录，必填——与 Claude 侧不同，Codex 没有 Workbench 实验
            联动那条 "auto-allocate workspace" 的路径（至少 5ba 阶段没有）。
        model : str
            默认 ``gpt-5.5``。调用方可覆盖但不会做 tier 分档。
        sandbox_mode : str
            ``"read-only" / "workspace-write" / "danger-full-access"`` 之一。

        Raises
        ------
        ValueError
            ``sandbox_mode`` 非法。
        CodexAuthError
            ``~/.codex/auth.json`` 缺失或不可读。
        """
        if sandbox_mode not in VALID_SANDBOX_MODES:
            raise ValueError(
                f"invalid sandbox_mode: {sandbox_mode!r} "
                f"(must be one of {sorted(VALID_SANDBOX_MODES)})"
            )
        _check_codex_auth(self._codex_home)

        session_id = uuid.uuid4().hex
        permission_state = PermissionState()
        cwd_str = str(cwd)

        client = await self._client_factory(
            session_id=session_id,
            cwd=cwd_str,
            model=model,
            sandbox_mode=sandbox_mode,
            permission_state=permission_state,
        )

        now = time.time()
        session = CodexSession(
            id=session_id,
            cwd=cwd_str,
            model=model,
            sandbox_mode=sandbox_mode,
            created_at=now,
            last_activity_at=now,
            client=client,
            permission_state=permission_state,
        )
        async with self._lock:
            self._sessions[session.id] = session
        self._ensure_sweeper()
        return session

    def get(self, session_id: str) -> CodexSession | None:
        return self._sessions.get(session_id)

    def touch(self, session_id: str) -> CodexSession | None:
        """原子刷新活跃时间戳并返回会话——语义同 ClaudeSessionManager.touch。"""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        session.last_activity_at = time.time()
        return session

    def list_sessions(self) -> list[CodexSession]:
        return list(self._sessions.values())

    async def get_or_restore(self, session_id: str) -> CodexSession | None:
        """查找会话。

        5ba 阶段仅在内存 dict 中查——Codex 侧的持久化 store（对应
        ``ClaudeCodeStore``）是后续任务范畴。当会话被 idle evict 或进程重启后，
        无法恢复；前端需要按 404 处理。返回 ``None`` 表示"当前进程内不存在"。
        """
        session = self._sessions.get(session_id)
        if session is not None:
            session.last_activity_at = time.time()
        return session

    async def delete(self, session_id: str) -> bool:
        """断开并移除会话。

        返回是否实际移除。``disconnect`` 失败不冒泡——注册表必须清理成功，
        留日志便于排障。与 idle evict 区分：delete 是"用户显式结束会话"，
        idle evict 是"长时无活动被动回收"。
        """
        async with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        _cancel_pending_permissions(session)
        try:
            await session.client.disconnect()
        except Exception:
            logger.exception("disconnect failed for codex session %s", session.id)
        return True

    async def interrupt(self, session_id: str) -> bool:
        """打断当前推理。返回会话是否存在；client 抛错向上传播由路由层转 5xx。"""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session.last_activity_at = time.time()
        await session.client.interrupt()
        return True

    def _ensure_sweeper(self) -> None:
        """首次注册会话时 lazy 启动 sweeper；已运行则 no-op。"""
        if self._sweeper_task is not None and not self._sweeper_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 同步测试场景——没有 event loop，放弃启动
            return
        self._sweeper_task = loop.create_task(
            self._sweep_loop(), name="codex-sweeper"
        )

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
                logger.exception("codex idle sweeper iteration failed")

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
            logger.info(
                "codex session %s evicted by idle ttl (>%.0fs)", session.id, ttl
            )
            _cancel_pending_permissions(session)
            try:
                await session.client.disconnect()
            except Exception:
                logger.exception(
                    "disconnect failed during idle eviction for codex %s",
                    session.id,
                )

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
                logger.exception(
                    "disconnect failed for codex session %s during shutdown",
                    session.id,
                )


def _cancel_pending_permissions(session: CodexSession) -> None:
    """会话关停前把所有悬挂的权限 Future 置为 deny，避免 bridge 协程死等。"""
    state = session.permission_state
    state.current_sse_emitter = None
    if not state.pending_requests:
        return
    pending = list(state.pending_requests.values())
    state.pending_requests.clear()
    for fut in pending:
        if not fut.done():
            fut.set_result({"decision": "deny", "message": "session closed"})


# 模块级单例——路由层 import 本名使用；测试可构造独立实例注入。
codex_session_manager = CodexSessionManager()
