from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable

from src.dynamic_os.policy.engine import PolicyEngine
from src.dynamic_os.tools.registry import ToolCapability, ToolDescriptor, ToolRegistry

ToolInvoker = Callable[[ToolDescriptor, dict[str, Any]], Awaitable[Any] | Any]


class McpGateway:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        policy: PolicyEngine,
        invoker: ToolInvoker | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._invoker = invoker

    async def invoke_tool(self, tool_id: str, payload: dict[str, Any]) -> Any:
        if self._invoker is None:
            raise RuntimeError("no MCP invoker configured")
        tool = self._registry.get(tool_id)
        self._policy.record_tool_invocation()
        result = self._invoker(tool, payload)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, dict):
            usage = result.get("usage")
            if isinstance(usage, dict):
                self._policy.record_tokens(int(usage.get("total_tokens") or 0))
            if "content" in result:
                return result.get("content")
        return result

    async def invoke_capability(
        self,
        capability: ToolCapability | str,
        payload: dict[str, Any],
        *,
        preferred: str = "auto",
    ) -> Any:
        tool = self._registry.resolve(capability, preferred=preferred)
        return await self.invoke_tool(tool.tool_id, payload)
