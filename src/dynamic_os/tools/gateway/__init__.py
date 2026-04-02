"""工具网关子包 — 统一工具执行层的入口。

本包包含所有子网关（LLM、搜索、检索、代码执行、文件系统）以及
ToolGateway / ContextualToolGateway 两个顶层网关类。

ToolGateway 是技能（skill）调用外部工具的唯一入口，负责：
- 将不同类型的工具调用分发到对应的子网关
- 通过 ContextualToolGateway 注入运行时上下文（run_id、skill_id 等）
- 基于 SkillPermissions 进行权限管控
- 发射 ToolInvokeEvent 事件供上层监听
"""

from __future__ import annotations

from typing import Callable

from src.dynamic_os.contracts.artifact import now_iso as _now_iso
from src.dynamic_os.contracts.events import ToolInvokeEvent
from src.dynamic_os.contracts.skill_spec import SkillPermissions
from src.dynamic_os.policy.engine import PolicyEngine, PolicyViolationError
from src.dynamic_os.tools.gateway.exec import CodeExecutor, ExecutionGateway
from src.dynamic_os.tools.gateway.filesystem import FilesystemGateway
from src.dynamic_os.tools.gateway.llm import LLMGateway
from src.dynamic_os.tools.gateway.mcp import McpGateway, ToolInvoker
from src.dynamic_os.tools.gateway.retrieval import RetrievalGateway
from src.dynamic_os.tools.gateway.search import SearchGateway
from src.dynamic_os.tools.registry import ToolCapability, ToolRegistry

# 事件接收器类型：接收任意事件对象的回调函数
EventSink = Callable[[object], None]


class ToolGateway:
    """所有技能的统一工具执行层。

    作为技能与外部工具之间的中间层，将各类工具调用请求分发到
    对应的子网关（LLM / 搜索 / 检索 / 执行 / 文件系统）。
    可通过 with_context / with_permissions / with_allowed_tools
    创建带上下文和权限约束的 ContextualToolGateway。
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        policy: PolicyEngine,
        mcp_invoker: ToolInvoker | None = None,
        code_executor: CodeExecutor | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self._registry = registry        # 工具注册表
        self._policy = policy            # 策略引擎
        self._event_sink = event_sink    # 事件接收器（可选）
        # 初始化各子网关
        self._mcp = McpGateway(registry=registry, policy=policy, invoker=mcp_invoker)
        self._llm = LLMGateway(self._mcp)
        self._search = SearchGateway(mcp=self._mcp, policy=policy)
        self._retrieval = RetrievalGateway(self._mcp)
        self._execution = ExecutionGateway(policy=policy, mcp=self._mcp, executor=code_executor)
        self._filesystem = FilesystemGateway(policy=policy)

    async def llm_chat(
        self,
        messages: list[dict[str, str]],
        *,
        provider: str = "",
        model: str = "",
        role_id: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str:
        """调用 LLM 聊天补全。"""
        return await self._llm.llm_chat(
            messages,
            provider=provider,
            model=model,
            role_id=role_id,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )

    async def search(
        self,
        query: str,
        *,
        source: str = "auto",
        max_results: int = 10,
    ) -> dict:
        """执行搜索（学术/网页）。"""
        return await self._search.search(query, source=source, max_results=max_results)

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        """执行向量检索。"""
        return await self._retrieval.retrieve(query, top_k=top_k, filters=filters)

    async def index(
        self,
        documents: list[dict],
        *,
        collection: str = "default",
    ) -> None:
        """将文档索引到指定集合。"""
        await self._retrieval.index(documents, collection=collection)

    async def execute_code(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_sec: int = 60,
        remote: bool = False,
    ) -> dict:
        """执行代码（沙箱/远程）。"""
        return await self._execution.execute_code(code, language=language, timeout_sec=timeout_sec, remote=remote)

    async def read_file(self, path: str) -> str:
        """读取文件内容。"""
        return await self._filesystem.read_file(path)

    async def write_file(self, path: str, content: str) -> None:
        """写入文件内容。"""
        await self._filesystem.write_file(path, content)

    def with_context(self, *, run_id: str, node_id: str, skill_id: str, role_id: str = "") -> "ContextualToolGateway":
        """创建带运行时上下文的网关实例。"""
        return ContextualToolGateway(self, run_id=run_id, node_id=node_id, skill_id=skill_id, role_id=role_id)

    def with_permissions(self, permissions: SkillPermissions) -> "ContextualToolGateway":
        """创建带权限约束的网关实例。"""
        return ContextualToolGateway(self, permissions=permissions)

    def with_allowed_tools(self, allowed_tools: list[str]) -> "ContextualToolGateway":
        """创建带工具白名单的网关实例。"""
        return ContextualToolGateway(self, allowed_tools=allowed_tools)

    def _emit(self, event: object) -> None:
        """发射事件到事件接收器。"""
        if self._event_sink is not None:
            self._event_sink(event)


class ContextualToolGateway:
    """带上下文和权限约束的工具网关。

    在 ToolGateway 基础上注入运行时上下文（run_id、node_id、skill_id）、
    技能权限（SkillPermissions）和工具白名单。每次工具调用前会进行权限校验，
    调用时自动发射 ToolInvokeEvent 事件。
    """

    def __init__(
        self,
        base: ToolGateway,
        *,
        run_id: str = "",
        node_id: str = "",
        skill_id: str = "",
        role_id: str = "",
        permissions: SkillPermissions | None = None,
        allowed_tools: list[str] | frozenset[str] | None = None,
    ) -> None:
        self._base = base                # 底层 ToolGateway
        self._run_id = run_id            # 当前运行 ID
        self._node_id = node_id          # 当前执行节点 ID
        self._skill_id = skill_id        # 当前技能 ID
        self._role_id = role_id          # 当前角色 ID
        self._permissions = permissions or SkillPermissions()  # 技能权限声明
        self._allowed_tools = None if allowed_tools is None else frozenset(allowed_tools)  # 工具白名单

    def with_context(self, *, run_id: str, node_id: str, skill_id: str, role_id: str = "") -> "ContextualToolGateway":
        """创建新的上下文网关（继承权限和白名单）。"""
        return ContextualToolGateway(
            self._base,
            run_id=run_id,
            node_id=node_id,
            skill_id=skill_id,
            role_id=role_id,
            permissions=self._permissions,
            allowed_tools=self._allowed_tools,
        )

    def with_permissions(self, permissions: SkillPermissions) -> "ContextualToolGateway":
        """创建新的上下文网关（替换权限声明）。"""
        return ContextualToolGateway(
            self._base,
            run_id=self._run_id,
            node_id=self._node_id,
            skill_id=self._skill_id,
            role_id=self._role_id,
            permissions=permissions,
            allowed_tools=self._allowed_tools,
        )

    def with_allowed_tools(self, allowed_tools: list[str]) -> "ContextualToolGateway":
        """创建新的上下文网关（替换工具白名单）。"""
        return ContextualToolGateway(
            self._base,
            run_id=self._run_id,
            node_id=self._node_id,
            skill_id=self._skill_id,
            role_id=self._role_id,
            permissions=self._permissions,
            allowed_tools=allowed_tools,
        )

    async def llm_chat(
        self,
        messages: list[dict[str, str]],
        *,
        provider: str = "",
        model: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str:
        """调用 LLM 聊天补全（带权限校验和事件发射）。"""
        tool_id = self._resolve_tool_id(ToolCapability.llm_chat)
        self._ensure_tool_allowed(tool_id)
        return await self._wrap_tool_call(
            tool_id,
            self._base.llm_chat(
                messages,
                provider=provider,
                model=model,
                role_id=self._role_id,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            ),
        )

    async def search(
        self,
        query: str,
        *,
        source: str = "auto",
        max_results: int = 10,
    ) -> dict:
        """执行搜索（带网络权限校验）。"""
        if not self._permissions.network:
            raise PolicyViolationError("skill does not allow network access")
        # 对特殊来源值不做偏好解析
        preferred_source = source if source not in {"", "auto", "academic", "web"} else "auto"
        tool_id = self._resolve_tool_id(ToolCapability.search, preferred=preferred_source)
        self._ensure_tool_allowed(tool_id)
        return await self._wrap_tool_call(
            tool_id,
            self._base.search(query, source=source, max_results=max_results),
        )

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        """执行向量检索（带网络权限校验）。"""
        if not self._permissions.network:
            raise PolicyViolationError("skill does not allow network access")
        tool_id = self._resolve_tool_id(ToolCapability.retrieve)
        self._ensure_tool_allowed(tool_id)
        return await self._wrap_tool_call(
            tool_id,
            self._base.retrieve(query, top_k=top_k, filters=filters),
        )

    async def index(
        self,
        documents: list[dict],
        *,
        collection: str = "default",
    ) -> None:
        """将文档索引到指定集合（带白名单校验）。"""
        tool_id = self._resolve_tool_id(ToolCapability.index)
        self._ensure_tool_allowed(tool_id)
        await self._wrap_tool_call(
            tool_id,
            self._base.index(documents, collection=collection),
        )

    async def execute_code(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_sec: int = 60,
        remote: bool = False,
    ) -> dict:
        """执行代码（带执行权限校验）。"""
        if remote:
            if not self._permissions.remote_exec:
                raise PolicyViolationError("skill does not allow remote execution")
        elif not self._permissions.sandbox_exec:
            raise PolicyViolationError("skill does not allow sandbox execution")
        tool_id = self._resolve_tool_id(
            ToolCapability.execute_code,
            preferred="remote_execute_code" if remote else "execute_code",
            fallback="mcp.exec.remote_execute_code" if remote else "mcp.exec.execute_code",
        )
        self._ensure_tool_allowed(tool_id)
        return await self._wrap_tool_call(
            tool_id,
            self._base.execute_code(code, language=language, timeout_sec=timeout_sec, remote=remote),
        )

    async def read_file(self, path: str) -> str:
        """读取文件（带文件系统读权限校验）。"""
        if not self._permissions.filesystem_read:
            raise PolicyViolationError("skill does not allow filesystem read")
        tool_id = self._resolve_tool_id(
            ToolCapability.read_file,
            fallback="mcp.filesystem.read_file",
        )
        self._ensure_tool_allowed(tool_id)
        return await self._wrap_tool_call(tool_id, self._base.read_file(path))

    async def write_file(self, path: str, content: str) -> None:
        """写入文件（带文件系统写权限校验）。"""
        if not self._permissions.filesystem_write:
            raise PolicyViolationError("skill does not allow filesystem write")
        tool_id = self._resolve_tool_id(
            ToolCapability.write_file,
            fallback="mcp.filesystem.write_file",
        )
        self._ensure_tool_allowed(tool_id)
        await self._wrap_tool_call(tool_id, self._base.write_file(path, content))

    async def _wrap_tool_call(self, tool_id: str, awaitable):
        """包装工具调用：在调用前后发射 start/end/error 事件。"""
        self._emit_tool_event(tool_id, "start")
        try:
            result = await awaitable
        except Exception:
            self._emit_tool_event(tool_id, "error")
            raise
        self._emit_tool_event(tool_id, "end")
        return result

    def _emit_tool_event(self, tool_id: str, phase: str) -> None:
        """构建并发射 ToolInvokeEvent 事件。"""
        self._base._emit(
            ToolInvokeEvent(
                ts=_now_iso(),
                run_id=self._run_id,
                node_id=self._node_id,
                skill_id=self._skill_id,
                tool_id=tool_id,
                phase=phase,
            )
        )

    def _resolve_tool_id(
        self,
        capability: ToolCapability,
        *,
        preferred: str = "auto",
        fallback: str | None = None,
    ) -> str:
        """从注册表中解析工具 ID，找不到时使用 fallback。"""
        try:
            return self._base._registry.resolve(capability, preferred=preferred).tool_id
        except ValueError:
            if fallback is None:
                raise
            return fallback

    def _ensure_tool_allowed(self, tool_id: str) -> None:
        """校验工具是否在白名单中（如果配置了白名单）。"""
        if self._allowed_tools is not None and tool_id not in self._allowed_tools:
            raise PolicyViolationError(f"tool is not allowed for skill: {tool_id}")
