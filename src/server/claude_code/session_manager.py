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
import os
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

from src.server.integrations.colab.mcp_server import (
    default_mcp_config as default_colab_mcp_config,
)
from src.server.integrations.experiment.mcp_server import (
    default_mcp_config as default_experiment_mcp_config,
)
from src.server.integrations.zotero.mcp_server import (
    default_mcp_config as default_zotero_mcp_config,
)
from src.server.workspace.mcp_server import (
    default_mcp_config as default_workspace_mcp_config,
)
from src.server.claude_code.agents import load_subagents_from_directory
from src.server.claude_code.providers import (
    ProviderConfig,
    build_env_for_provider,
    get_provider_registry,
)
from src.server.claude_code.storage import ClaudeCodeStore

# 仓库根——用于给 MCP bridge 子进程传 --root / cwd
_REPO_ROOT = Path(__file__).resolve().parents[3]

logger = logging.getLogger(__name__)

# 与 SDK 字面量一致，禁止前端传入 "strict" 这种非 SDK 合法值
VALID_PERMISSION_MODES: frozenset[str] = frozenset(
    {"default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"}
)

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
        SDK ``PermissionMode`` 字面量之一。仅 ``"default"`` 时 SDK 会调用 can_use_tool
        桥触发前端 Modal，其余模式沿用 SDK 原生语义（acceptEdits 自动放行编辑工具等）；
        桥本身无条件挂载，保证运行时 /permissions 切换进/出 default 都立即生效。
    created_at : float
        创建 Unix 时间戳。
    last_activity_at : float
        最近一次活动（send_message / interrupt）时间戳，驱动 idle TTL 回收。
    client : ClaudeSDKClient
        已 ``connect`` 的 SDK 客户端。
    add_dirs : list[str]
        ``/add-dir`` 命令累计追加的额外工作目录，rebuild 时再次透传给 SDK。
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
    add_dirs: list[str] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    permission_state: PermissionState = field(default_factory=PermissionState)
    # 多 provider 支持（Task 1b）——None 表示"未选择 provider，走 Anthropic 默认零变更"。
    # 字符串为 registry 里的 provider 名（如 "anthropic" / "deepseek"），仅此外不回传 api_key。
    provider: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "cwd": self.cwd,
            "model": self.model,
            "permission_mode": self.permission_mode,
            "created_at": self.created_at,
            "add_dirs": list(self.add_dirs),
            "provider": self.provider,
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
        store: ClaudeCodeStore | None = None,
    ) -> None:
        self._sessions: dict[str, ClaudeSession] = {}
        self._lock = asyncio.Lock()
        self.idle_ttl_sec = idle_ttl_sec
        self.sweep_interval_sec = sweep_interval_sec
        self._sweeper_task: asyncio.Task[None] | None = None
        # 持久化 store；None = 禁用（测试场景或首次未接入路径）。所有 store.* 调用
        # 必须先检查 _store is not None，避免测试注入空 store 时崩溃。
        self._store = store

    @property
    def store(self) -> ClaudeCodeStore | None:
        return self._store

    async def create(
        self,
        cwd: str | Path,
        *,
        model: str | None = None,
        permission_mode: str = "default",
        options_overrides: dict[str, Any] | None = None,
        provider: str | None = None,
    ) -> ClaudeSession:
        """新建并 ``connect`` 一个 SDK 会话。

        Parameters
        ----------
        cwd : str or Path
            子进程工作目录。路由层负责合法性校验。
        model : str or None
            可选模型覆盖。
        permission_mode : str
            SDK PermissionMode 字面量，默认 ``"default"``（每次弹 Modal）。传入
            非法值会 raise ValueError。仅 ``"default"`` 模式注入 can_use_tool 桥。
        options_overrides : dict or None
            透传给 ``ClaudeAgentOptions`` 的额外字段（未来支持 system_prompt、mcp_servers 等)。
        provider : str or None
            registry 里的 provider 名；``None`` 表示不走 registry，沿用 Anthropic 默认
            env（零变更路径）。非 ``None`` 时查 ``get_provider_registry()`` 决议 env 注入；
            未知名 raise ValueError。``api_key_env`` 对应的 env 未设置也 raise。
        """
        if permission_mode not in VALID_PERMISSION_MODES:
            raise ValueError(
                f"invalid permission_mode: {permission_mode!r} "
                f"(must be one of {sorted(VALID_PERMISSION_MODES)})"
            )

        provider_config = _resolve_provider_or_raise(provider)

        session_id = uuid.uuid4().hex
        permission_state = PermissionState()

        client = await _build_client(
            session_id=session_id,
            cwd=cwd,
            model=model,
            permission_mode=permission_mode,
            add_dirs=[],
            permission_state=permission_state,
            options_overrides=options_overrides,
            sdk_resume=False,
            provider_config=provider_config,
        )

        now = time.time()
        session = ClaudeSession(
            id=session_id,
            cwd=str(cwd),
            model=model,
            permission_mode=permission_mode,
            created_at=now,
            last_activity_at=now,
            client=client,
            add_dirs=[],
            permission_state=permission_state,
            provider=provider,
        )
        async with self._lock:
            self._sessions[session.id] = session
        if self._store is not None:
            # 让新行跟 SDK 指定的 session_id 对齐。insert 失败视为致命错误直接上抛——
            # 比悄悄 DB 无记录但内存有 session 更诚实（后续 record_event 也会失败）。
            self._store.insert_session(
                session_id=session_id,
                cwd=str(cwd),
                model=model,
                permission_mode=permission_mode,
                add_dirs=[],
                provider=provider,
            )
        self._ensure_sweeper()
        return session

    async def clear_context(self, session_id: str) -> ClaudeSession | None:
        """清空会话上下文：dispose 旧 SDK client 并重建同 id 新 client（不 resume）。

        - 保留 ``add_dirs`` 累计目录（用户的"工作区"配置不该被 /clear 抹掉）
        - 保留 ``permission_state.allowed_always``（"允许本会话"属于用户信任选择
          而非上下文，/clear 只清对话历史不清权限授权，与 CLI 语义一致）
        - 刷新 ``last_activity_at``，保留原 ``created_at``
        - DB 侧清空该 session 的 messages 行（``store.clear_messages``），保留
          sessions 行的元数据。与 SDK 侧"同 id 不 resume 重建"语义对齐

        Returns
        -------
        ClaudeSession or None
            重建后的会话；若 id 不存在返回 ``None``。
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None
        old_client = session.client
        _cancel_pending_permissions(session)
        try:
            await old_client.disconnect()
        except Exception:
            logger.exception("disconnect failed during clear_context for %s", session_id)

        new_client = await _build_client(
            session_id=session_id,
            cwd=session.cwd,
            model=session.model,
            permission_mode=session.permission_mode,
            add_dirs=list(session.add_dirs),
            permission_state=session.permission_state,
            options_overrides=None,
            sdk_resume=False,
            provider_config=_resolve_provider_or_raise(session.provider),
        )
        session.client = new_client
        session.last_activity_at = time.time()
        if self._store is not None:
            self._store.clear_messages(session_id)
        return session

    async def add_directory(self, session_id: str, path: str) -> ClaudeSession | None:
        """把 ``path`` 加入会话的 ``add_dirs`` 并重建 SDK client（带 resume 保留上下文）。

        SDK 的 ``ClaudeAgentOptions.add_dirs`` 只在 client 初始化时生效，没有运行时
        mutator——所以追加目录必须重建 client。重建路径传 ``sdk_resume=True``，
        SDK 从本地 session 存档回放历史到新 client，用户继续对话时上下文完整。

        路径校验（存在 + 属于项目根）由路由层完成；SessionManager 只负责 append
        + rebuild。DB 侧同步 ``update_add_dirs``。

        Returns
        -------
        ClaudeSession or None
            重建后的会话；若 id 不存在返回 ``None``。
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if path in session.add_dirs:
            # 幂等：目录已在列表中就不重建
            session.last_activity_at = time.time()
            return session

        old_client = session.client
        new_add_dirs = [*session.add_dirs, path]
        _cancel_pending_permissions(session)
        try:
            await old_client.disconnect()
        except Exception:
            logger.exception("disconnect failed during add_directory for %s", session_id)

        new_client = await _build_client(
            session_id=session_id,
            cwd=session.cwd,
            model=session.model,
            permission_mode=session.permission_mode,
            add_dirs=new_add_dirs,
            permission_state=session.permission_state,
            options_overrides=None,
            sdk_resume=True,
            provider_config=_resolve_provider_or_raise(session.provider),
        )
        session.client = new_client
        session.add_dirs = new_add_dirs
        session.last_activity_at = time.time()
        if self._store is not None:
            self._store.update_add_dirs(session_id, new_add_dirs)
        return session

    async def switch_model(
        self, session_id: str, model: str | None
    ) -> ClaudeSession | None:
        """切换会话模型，SDK 运行时调用 ``set_model`` 保留上下文。

        传入 ``None`` 表示重置为 CLI 默认模型。SDK 未校验模型字符串，非法值会在
        下一次 query 时由子进程报错——路由层若需前置校验应自行把 ``/models``
        返回的白名单做 membership 检查。

        ``set_model`` 会向 SDK 子进程写 stdin 帧；为避免与 ``send_message`` 的
        ``query/receive_response`` 并发造成帧交错，整段 SDK 调用持会话锁。

        Returns
        -------
        ClaudeSession or None
            更新后的会话；若 id 不存在返回 ``None``。
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None
        async with session.lock:
            await session.client.set_model(model)
            session.model = model
            session.last_activity_at = time.time()
        if self._store is not None:
            self._store.update_model(session_id, model)
        return session

    async def switch_permission_mode(
        self, session_id: str, mode: str
    ) -> ClaudeSession | None:
        """切换会话权限模式，SDK 运行时调用 ``set_permission_mode`` 保留上下文。

        非法 mode 显式 ``raise ValueError``；这是运行期契约而不是开发期断言，
        故不能用 ``assert``（会被 ``python -O`` 优化掉）。``set_permission_mode``
        会向 SDK 子进程写 stdin 帧，调用前后持会话锁避免与 ``query`` 帧交错。

        Returns
        -------
        ClaudeSession or None
            更新后的会话；若 id 不存在返回 ``None``。
        """
        if mode not in VALID_PERMISSION_MODES:
            raise ValueError(
                f"invalid permission_mode {mode!r} "
                f"(must be one of {sorted(VALID_PERMISSION_MODES)})"
            )
        session = self._sessions.get(session_id)
        if session is None:
            return None
        async with session.lock:
            await session.client.set_permission_mode(mode)
            session.permission_mode = mode
            session.last_activity_at = time.time()
        if self._store is not None:
            self._store.update_permission_mode(session_id, mode)
        return session

    async def get_mcp_status(self, session_id: str) -> dict[str, Any] | None:
        """读取会话挂载的 MCP server 状态，委托给 SDK ``get_mcp_status``。

        ``get_mcp_status`` 走 SDK 子进程的 request/response，同样需要持会话锁
        避免与当前轮 ``query/receive_response`` 的 stdin/stdout 帧交错。

        Returns
        -------
        dict or None
            SDK 返回的原始响应；若 id 不存在返回 ``None``。未挂任何 server 时
            返回 ``{"mcpServers": []}`` 形状的空列表，由前端展示"无挂载"。
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None
        async with session.lock:
            session.last_activity_at = time.time()
            return await session.client.get_mcp_status()

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
        """断开并移除会话，同步清理 DB。返回是否实际删除了会话。

        删除语义：用户显式"结束会话"——永久销毁，memory + DB 都清。
        与 idle evict 区分：后者仅清 memory 保 DB 历史供刷新恢复。
        """
        async with self._lock:
            session = self._sessions.pop(session_id, None)
        # DB 侧无论 memory 是否命中都清——允许删除"已被 evict 仅剩 DB 行"的会话
        had_db_row = False
        if self._store is not None:
            had_db_row = self._store.delete_session(session_id)
        if session is None:
            return had_db_row
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

    async def get_or_restore(self, session_id: str) -> ClaudeSession | None:
        """查找会话；若仅存在于 DB（被 idle evict 或进程重启），按 metadata rebuild。

        恢复路径传 ``sdk_resume=True``——SDK 从 ``~/.claude/projects/<cwd>/<uuid>.jsonl``
        回放 CLI 本地存档到新 client，用户后续 send_message 时上下文完整。DB 的
        messages 表只负责前端 UI 历史回灌（``GET /sessions/{id}/messages``），不参与
        SDK 侧上下文重建——真相单一源在 CLI 存档。

        Returns
        -------
        ClaudeSession or None
            ``None`` 表示 DB 也查不到该 id（真的不存在）。
        """
        session = self._sessions.get(session_id)
        if session is not None:
            session.last_activity_at = time.time()
            return session
        if self._store is None:
            return None
        stored = self._store.get_session(session_id)
        if stored is None:
            return None
        permission_state = PermissionState()
        client = await _build_client(
            session_id=session_id,
            cwd=stored.cwd,
            model=stored.model,
            permission_mode=stored.permission_mode,
            add_dirs=list(stored.add_dirs),
            permission_state=permission_state,
            options_overrides=None,
            sdk_resume=True,
            provider_config=_resolve_provider_or_raise(stored.provider),
        )
        now = time.time()
        session = ClaudeSession(
            id=session_id,
            cwd=stored.cwd,
            model=stored.model,
            permission_mode=stored.permission_mode,
            created_at=stored.created_at,
            last_activity_at=now,
            client=client,
            add_dirs=list(stored.add_dirs),
            permission_state=permission_state,
            provider=stored.provider,
        )
        async with self._lock:
            # 在 await connect 期间若并发请求已恢复过，让那次的 session 胜出，把
            # 我们刚建的 client disconnect 掉——避免 CLI 双开同一 session id 的档案。
            existing = self._sessions.get(session_id)
            if existing is not None:
                try:
                    await client.disconnect()
                except Exception:
                    logger.exception("disconnect failed for lost-race restore %s", session_id)
                existing.last_activity_at = now
                return existing
            self._sessions[session_id] = session
        self._ensure_sweeper()
        return session

    def record_event(
        self,
        session_id: str,
        *,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """把一条 SSE 事件序列化后落库。路由层在每次 emit 后调用。

        对 ``cc_message`` 且 payload.type == "result" 的事件，额外从 usage/cost
        字段累加到 sessions 行；其余事件只写 messages。DB 未配置时 no-op。
        """
        if self._store is None:
            return
        seq = self._store.append_message(
            session_id, event_type=event_type, payload=payload
        )
        if seq < 0:
            # session 行已被删除（比如用户 DELETE 后还在收尾帧）——静默丢弃
            return
        if event_type != "cc_message":
            return
        if payload.get("type") != "result":
            return
        usage = payload.get("usage") or {}
        if not isinstance(usage, dict):
            return
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        cost_usd = payload.get("total_cost_usd") or 0.0
        try:
            cost_usd = float(cost_usd)
        except (TypeError, ValueError):
            cost_usd = 0.0
        self._store.accumulate_usage(
            session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )

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
        if self._store is not None:
            try:
                self._store.close()
            except Exception:
                logger.exception("claude code store close failed during shutdown")


async def _build_client(
    *,
    session_id: str,
    cwd: str | Path,
    model: str | None,
    permission_mode: str,
    add_dirs: list[str],
    permission_state: PermissionState,
    options_overrides: dict[str, Any] | None,
    sdk_resume: bool,
    provider_config: ProviderConfig | None = None,
) -> ClaudeSDKClient:
    """组装 ``ClaudeAgentOptions`` → 实例化 ``ClaudeSDKClient`` → ``connect``。

    Parameters
    ----------
    session_id : str
        后端分配的 UUID，同时作为 permission bridge 的凭据、SDK 侧的 session 标识。
    sdk_resume : bool
        ``False`` 表示创建新 SDK session（透传 ``session_id=<uuid>``，SDK 用我们的
        UUID 作为它自己的 session id，确保后续 ``resume`` 可找到 CLI 本地存档）。
        ``True`` 表示恢复旧 session（透传 ``resume=<uuid>``，SDK 从 ``~/.claude/``
        下对应目录的本地存档里回放历史到新 client，用户随后发消息时上下文完整）。
        两个参数互斥，不同时传。

    create 与 clear_context / add_directory / get_or_restore 的 rebuild 路径共用此
    工厂，保证 options 组装规则（permission bridge 注入、setting_sources 限制、
    add_dirs 透传、session_id/resume 互斥写法）只有一处真相。调用方确保
    ``permission_mode`` 合法（create 侧入口已校验）。
    """
    options_kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "permission_mode": permission_mode,
    }
    if model:
        options_kwargs["model"] = model
    if add_dirs:
        options_kwargs["add_dirs"] = list(add_dirs)
    if sdk_resume:
        options_kwargs["resume"] = session_id
    else:
        options_kwargs["session_id"] = session_id
    # 无条件挂桥接：SDK 仅在 permission_mode == "default" 时调用 can_use_tool，
    # 但运行时 /permissions 切换进/出 default 需要桥接随时可用；挂上是等价改动。
    # 配合仅加载 user 层设置，跳过项目 .claude/settings.json 的 allow-list，
    # 否则 Write/Edit/Bash 等被项目预批的工具会直接放行，default 模式下
    # can_use_tool 桥永远不被触发，Workbench 的 Modal 就失去存在意义。
    options_kwargs["can_use_tool"] = _build_permission_bridge(
        session_id, permission_state
    )
    options_kwargs.setdefault("setting_sources", ["user"])
    # Task 3 — subagent 程序化注入（DP1 fallback）：
    # setting_sources=["user"] 排除 project 层，CLI 不会自动发现 .claude/agents/*.md；
    # 显式把定义读进来塞进 ``options.agents``，效果等价于项目级 subagent。
    subagents = _load_subagents_cached()
    if subagents:
        options_kwargs["agents"] = dict(subagents)
    # 多 provider 支持（Task 1b）——传入 provider_config 时按其 base_url + api_key_env
    # 解析值写入 SDK 子进程 env。未传则 options_kwargs 不带 env，走 Anthropic 默认。
    if provider_config is not None:
        provider_env = build_env_for_provider(provider_config)
        # Stage 1 — env override 替换式语义会丢掉 MAMBA_ACTIVE_PROJECT_PATH（MCP
        # 子进程依赖此 env 定位 active project）。这里显式 propagate；其他对
        # MCP 必要的 env（PYTHONPATH 等已在各 mcp_server 模块的 default_mcp_config
        # 注入子进程层面）。
        mamba_active = os.environ.get("MAMBA_ACTIVE_PROJECT_PATH")
        if mamba_active:
            provider_env.setdefault("MAMBA_ACTIVE_PROJECT_PATH", mamba_active)
        options_kwargs["env"] = provider_env
    # 默认挂载 MambaResearch 内置 MCP servers：
    #   - mamba_workspace: 文件分类索引 server
    #   - zotero / colab / experiment: Stage 4 三个外部集成
    # overrides 里的 mcp_servers 与之合并，同名键由 overrides 胜出，便于测试
    # 关闭 / 替换某一个 server。
    bridge_config: dict[str, Any] = {}
    bridge_config.update(default_workspace_mcp_config(_REPO_ROOT))
    bridge_config.update(default_zotero_mcp_config(_REPO_ROOT))
    bridge_config.update(default_colab_mcp_config(_REPO_ROOT))
    bridge_config.update(default_experiment_mcp_config(_REPO_ROOT))
    if bridge_config:
        options_kwargs["mcp_servers"] = dict(bridge_config)
    if options_overrides:
        override_mcp = options_overrides.get("mcp_servers")
        if isinstance(override_mcp, dict) and isinstance(
            options_kwargs.get("mcp_servers"), dict,
        ):
            merged = dict(options_kwargs["mcp_servers"])
            merged.update(override_mcp)
            options_kwargs.update(options_overrides)
            options_kwargs["mcp_servers"] = merged
        else:
            options_kwargs.update(options_overrides)

    options = ClaudeAgentOptions(**options_kwargs)
    client = ClaudeSDKClient(options=options)
    await client.connect()
    return client


_cached_subagents: dict[str, Any] | None = None


def _load_subagents_cached() -> dict[str, Any]:
    """进程内单例 subagent registry——从 ``<repo>/.claude/agents/*.md`` 加载一次。

    解析失败直接抛 ``AgentDefinitionError``——启动期失败比运行时 SDK 崩溃可读得多。
    测试场景要刷新缓存时通过 monkeypatch ``_cached_subagents = None`` 或用
    ``load_subagents_from_directory`` 拿新值。
    """
    global _cached_subagents
    if _cached_subagents is None:
        _cached_subagents = load_subagents_from_directory(
            _REPO_ROOT / ".claude" / "agents"
        )
    return _cached_subagents


def _resolve_provider_or_raise(provider: str | None) -> ProviderConfig | None:
    """按名查 registry。``None`` → ``None``（零变更路径）；未知名 raise ValueError。

    集中化解析逻辑——create / clear_context / add_directory / get_or_restore 都
    经同一入口，防止 rebuild 路径漏传 provider 导致 env override 静默丢失。
    """
    if provider is None:
        return None
    registry = get_provider_registry()
    if provider not in registry:
        raise ValueError(
            f"unknown provider {provider!r} "
            f"(must be one of {sorted(registry.keys())})"
        )
    return registry[provider]


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


_DEFAULT_DB_PATH = Path(".tmp") / "claude_code" / "sessions.db"
session_manager = SessionManager(store=ClaudeCodeStore(_DEFAULT_DB_PATH))
