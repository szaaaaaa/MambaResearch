from __future__ import annotations

from typing import Any

from src.dynamic_os.policy.engine import PolicyEngine
from src.dynamic_os.tools.gateway.mcp import McpGateway
from src.dynamic_os.tools.registry import ToolCapability


class SearchGateway:
    def __init__(self, *, mcp: McpGateway, policy: PolicyEngine) -> None:
        self._mcp = mcp
        self._policy = policy

    async def search(
        self,
        query: str,
        *,
        source: str = "auto",
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        self._policy.assert_network_allowed()
        result = await self._mcp.invoke_capability(
            ToolCapability.search,
            {"query": query, "max_results": max_results},
            preferred=source,
        )
        return list(result)

