"""LLM 网关模块 — 封装大语言模型的聊天补全调用。

本模块通过 MCP 网关将 LLM 聊天请求转发给底层的 LLM MCP 服务器。
上层技能（skill）通过本网关进行 LLM 交互，无需关心具体的模型提供商和协议细节。
"""

from __future__ import annotations

from typing import Any

from src.dynamic_os.tools.gateway.mcp import McpGateway
from src.dynamic_os.tools.registry import ToolCapability


class LLMGateway:
    """LLM 网关 — 将聊天补全请求代理到 MCP 层。

    作为技能与 LLM 之间的桥梁，将消息列表和生成参数封装为
    MCP 调用 payload，通过 McpGateway 转发给 LLM 服务器。
    """

    def __init__(self, mcp: McpGateway) -> None:
        self._mcp = mcp  # 底层 MCP 网关，负责实际的工具调用

    async def llm_chat(
        self,
        messages: list[dict[str, str]],
        *,
        provider: str = "",
        model: str = "",
        role_id: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """发送聊天消息并获取 LLM 回复。

        参数
        ----------
        messages : list[dict[str, str]]
            消息列表，每条消息包含 role 和 content。
        provider : str, optional
            LLM 提供商名称（如 openai、gemini 等）。
        model : str, optional
            模型名称。
        role_id : str, optional
            角色 ID，用于从配置中解析对应的 provider/model。
        temperature : float, optional
            生成温度，默认 0.3。
        max_tokens : int, optional
            最大输出 token 数，默认 4096。
        response_format : dict, optional
            结构化输出的 JSON Schema，为 None 时使用普通文本输出。

        返回
        -------
        str
            LLM 返回的文本内容。
        """
        result = await self._mcp.invoke_capability(
            ToolCapability.llm_chat,
            {
                "messages": messages,
                "provider": provider,
                "model": model,
                "role_id": role_id,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": response_format,
            },
        )
        return str(result)
