from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

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

EventSink = Callable[[object], None]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ToolGateway:
    """Unified tool execution layer for all skills."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        policy: PolicyEngine,
        mcp_invoker: ToolInvoker | None = None,
        code_executor: CodeExecutor | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._event_sink = event_sink
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
        return await self._search.search(query, source=source, max_results=max_results)

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        return await self._retrieval.retrieve(query, top_k=top_k, filters=filters)

    async def index(
        self,
        documents: list[dict],
        *,
        collection: str = "default",
    ) -> None:
        await self._retrieval.index(documents, collection=collection)

    async def execute_code(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_sec: int = 60,
        remote: bool = False,
    ) -> dict:
        return await self._execution.execute_code(code, language=language, timeout_sec=timeout_sec, remote=remote)

    async def read_file(self, path: str) -> str:
        return await self._filesystem.read_file(path)

    async def write_file(self, path: str, content: str) -> None:
        await self._filesystem.write_file(path, content)

    def with_context(self, *, run_id: str, node_id: str, skill_id: str, role_id: str = "") -> "ContextualToolGateway":
        return ContextualToolGateway(self, run_id=run_id, node_id=node_id, skill_id=skill_id, role_id=role_id)

    def with_permissions(self, permissions: SkillPermissions) -> "ContextualToolGateway":
        return ContextualToolGateway(self, permissions=permissions)

    def with_allowed_tools(self, allowed_tools: list[str]) -> "ContextualToolGateway":
        return ContextualToolGateway(self, allowed_tools=allowed_tools)

    def _emit(self, event: object) -> None:
        if self._event_sink is not None:
            self._event_sink(event)


class ContextualToolGateway:
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
        self._base = base
        self._run_id = run_id
        self._node_id = node_id
        self._skill_id = skill_id
        self._role_id = role_id
        self._permissions = permissions or SkillPermissions()
        self._allowed_tools = None if allowed_tools is None else frozenset(allowed_tools)

    def with_context(self, *, run_id: str, node_id: str, skill_id: str, role_id: str = "") -> "ContextualToolGateway":
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
        if not self._permissions.network:
            raise PolicyViolationError("skill does not allow network access")
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
        if not self._permissions.filesystem_read:
            raise PolicyViolationError("skill does not allow filesystem read")
        tool_id = self._resolve_tool_id(
            ToolCapability.read_file,
            fallback="mcp.filesystem.read_file",
        )
        self._ensure_tool_allowed(tool_id)
        return await self._wrap_tool_call(tool_id, self._base.read_file(path))

    async def write_file(self, path: str, content: str) -> None:
        if not self._permissions.filesystem_write:
            raise PolicyViolationError("skill does not allow filesystem write")
        tool_id = self._resolve_tool_id(
            ToolCapability.write_file,
            fallback="mcp.filesystem.write_file",
        )
        self._ensure_tool_allowed(tool_id)
        await self._wrap_tool_call(tool_id, self._base.write_file(path, content))

    async def _wrap_tool_call(self, tool_id: str, awaitable):
        self._emit_tool_event(tool_id, "start")
        try:
            result = await awaitable
        except Exception:
            self._emit_tool_event(tool_id, "error")
            raise
        self._emit_tool_event(tool_id, "end")
        return result

    def _emit_tool_event(self, tool_id: str, phase: str) -> None:
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
        try:
            return self._base._registry.resolve(capability, preferred=preferred).tool_id
        except ValueError:
            if fallback is None:
                raise
            return fallback

    def _ensure_tool_allowed(self, tool_id: str) -> None:
        if self._allowed_tools is not None and tool_id not in self._allowed_tools:
            raise PolicyViolationError(f"tool is not allowed for skill: {tool_id}")
