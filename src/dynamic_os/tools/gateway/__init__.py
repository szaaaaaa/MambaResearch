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
from src.dynamic_os.tools.gateway.mcp import ContextualMcpGateway, McpGateway, ToolInvoker
from src.dynamic_os.tools.gateway.retrieval import RetrievalGateway
from src.dynamic_os.tools.gateway.search import SearchGateway
from src.dynamic_os.tools.registry import ToolRegistry

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
        self._registry = registry            # 工具注册表
        self._policy = policy                # 策略引擎
        self._event_sink = event_sink        # 事件接收器（可选）
        self._code_executor = code_executor  # 自定义代码执行器（供 ContextualToolGateway 复用）
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
        academic_sources: list[str] | None = None,
    ) -> dict:
        """执行搜索（学术/网页）。"""
        return await self._search.search(
            query, source=source, max_results=max_results, academic_sources=academic_sources,
        )

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
    技能权限（SkillPermissions）和工具白名单。

    白名单校验和 ToolInvokeEvent 事件发射下沉到 :class:`ContextualMcpGateway`，
    由它在每次 MCP 工具调用的真实入口处完成，从而避免"上层按能力解析出
    工具 A、下层实际调用工具 B"时白名单判错的问题。文件系统读写和自定义
    代码执行器不经过 MCP，仅由 SkillPermissions 管控；若走 MCP 回退路径，
    依然由 ContextualMcpGateway 做白名单校验。
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
        self._base = base                # 底层 ToolGateway（提供 registry/policy/事件出口）
        self._run_id = run_id            # 当前运行 ID
        self._node_id = node_id          # 当前执行节点 ID
        self._skill_id = skill_id        # 当前技能 ID
        self._role_id = role_id          # 当前角色 ID
        self._permissions = permissions or SkillPermissions()  # 技能权限声明
        # 工具白名单（None 表示不限制）
        self._allowed_tools = None if allowed_tools is None else frozenset(allowed_tools)

        # 构造带白名单校验和事件发射的 MCP 网关
        contextual_mcp = ContextualMcpGateway(
            base._mcp,
            allowed_tools=self._allowed_tools,
            event_emitter=self._emit_tool_event,
        )
        # 所有涉及 MCP 调用的子网关都改用 ContextualMcpGateway
        self._llm = LLMGateway(contextual_mcp)
        self._search = SearchGateway(mcp=contextual_mcp, policy=base._policy)
        self._retrieval = RetrievalGateway(contextual_mcp)
        self._execution = ExecutionGateway(
            policy=base._policy,
            mcp=contextual_mcp,
            executor=base._code_executor,
        )
        # 文件系统网关直接使用本地文件 I/O，不经 MCP
        self._filesystem = base._filesystem

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
        """调用 LLM 聊天补全。白名单与事件由 ContextualMcpGateway 处理。"""
        return await self._llm.llm_chat(
            messages,
            provider=provider,
            model=model,
            role_id=self._role_id,
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
        academic_sources: list[str] | None = None,
    ) -> dict:
        """执行搜索（带网络权限校验，具体工具白名单下沉到 MCP 层）。"""
        if not self._permissions.network:
            raise PolicyViolationError("skill does not allow network access")
        return await self._search.search(
            query, source=source, max_results=max_results, academic_sources=academic_sources,
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
        """执行代码（带执行权限校验）。

        自定义 CodeExecutor 不经过 MCP，由 sandbox_exec/remote_exec 权限独立把关；
        回退到 MCP 路径时，ContextualMcpGateway 会校验工具白名单。
        """
        if remote:
            if not self._permissions.remote_exec:
                raise PolicyViolationError("skill does not allow remote execution")
        elif not self._permissions.sandbox_exec:
            raise PolicyViolationError("skill does not allow sandbox execution")
        return await self._execution.execute_code(
            code, language=language, timeout_sec=timeout_sec, remote=remote,
        )

    async def read_file(self, path: str) -> str:
        """读取文件（带文件系统读权限校验）。"""
        if not self._permissions.filesystem_read:
            raise PolicyViolationError("skill does not allow filesystem read")
        return await self._filesystem.read_file(path)

    async def write_file(self, path: str, content: str) -> None:
        """写入文件（带文件系统写权限校验）。"""
        if not self._permissions.filesystem_write:
            raise PolicyViolationError("skill does not allow filesystem write")
        await self._filesystem.write_file(path, content)

    def _emit_tool_event(self, tool_id: str, phase: str) -> None:
        """构建并发射 ToolInvokeEvent（作为 ContextualMcpGateway 的回调）。"""
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
