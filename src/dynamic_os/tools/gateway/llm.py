from __future__ import annotations

from typing import Any

from src.dynamic_os.tools.gateway.mcp import McpGateway
from src.dynamic_os.tools.registry import ToolCapability


class LLMGateway:
    def __init__(self, mcp: McpGateway) -> None:
        self._mcp = mcp

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
