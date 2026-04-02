"""MCP 网关模块 — 统一代理所有 MCP 工具调用。

本模块是工具网关的最底层代理，负责将上层网关（LLM、搜索、检索、执行等）
的调用请求转发给实际的 MCP 服务器进程。

核心职责：
- 通过 ToolInvoker 回调函数调用 MCP 工具
- 自动记录工具调用次数和 token 消耗（通过 PolicyEngine）
- 支持按 tool_id 精确调用或按能力类型自动解析调用
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable

from src.dynamic_os.policy.engine import PolicyEngine
from src.dynamic_os.tools.registry import ToolCapability, ToolDescriptor, ToolRegistry

# ToolInvoker 签名：接收工具描述符和参数字典，返回调用结果
# 支持同步和异步两种调用方式
ToolInvoker = Callable[[ToolDescriptor, dict[str, Any]], Awaitable[Any] | Any]


class McpGateway:
    """MCP 网关 — 所有 MCP 工具调用的统一代理层。

    接收上层网关传入的调用请求，通过 invoker 回调函数转发给实际的 MCP 服务端，
    同时在策略引擎中记录调用次数和 token 用量。
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        policy: PolicyEngine,
        invoker: ToolInvoker | None = None,
    ) -> None:
        self._registry = registry    # 工具注册表，用于查找工具描述符
        self._policy = policy        # 策略引擎，用于记录调用和 token 消耗
        self._invoker = invoker      # 实际的 MCP 调用回调函数

    async def invoke_tool(self, tool_id: str, payload: dict[str, Any]) -> Any:
        """按 tool_id 调用指定的 MCP 工具。

        参数
        ----------
        tool_id : str
            工具唯一标识，格式为 ``mcp.<server_id>.<tool_name>``。
        payload : dict[str, Any]
            传递给工具的参数字典。

        返回
        -------
        Any
            工具返回的内容。如果返回结构中包含 "content" 字段，
            则自动提取该字段作为最终结果。

        异常
        ------
        RuntimeError
            当未配置 invoker 时抛出。
        """
        if self._invoker is None:
            raise RuntimeError("no MCP invoker configured")
        tool = self._registry.get(tool_id)
        # 记录一次工具调用
        self._policy.record_tool_invocation()
        result = self._invoker(tool, payload)
        # 兼容同步和异步 invoker
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, dict):
            # 提取 token 用量信息并记录到策略引擎
            usage = result.get("usage")
            if isinstance(usage, dict):
                self._policy.record_tokens(int(usage.get("total_tokens") or 0))
            # 如果返回结构包含 "content"，只返回内容部分
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
        """按能力类型调用工具（自动从注册表中解析具体工具）。

        参数
        ----------
        capability : ToolCapability | str
            目标能力类型。
        payload : dict[str, Any]
            传递给工具的参数字典。
        preferred : str, optional
            偏好的工具名称或 ID，默认 "auto"。

        返回
        -------
        Any
            工具返回的内容。
        """
        tool = self._registry.resolve(capability, preferred=preferred)
        return await self.invoke_tool(tool.tool_id, payload)
