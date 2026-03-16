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
    ) -> dict[str, list[dict[str, Any]] | list[str]]:
        self._policy.assert_network_allowed()
        preferred_source = source if source not in {"", "auto", "academic", "web"} else "auto"
        result = await self._mcp.invoke_capability(
            ToolCapability.search,
            {"query": query, "source": source, "max_results": max_results},
            preferred=preferred_source,
        )
        if isinstance(result, dict):
            return {
                "results": [dict(item) for item in result.get("results", []) if isinstance(item, dict)],
                "warnings": [str(item).strip() for item in result.get("warnings", []) if str(item).strip()],
            }
        return {
            "results": [dict(item) for item in result if isinstance(item, dict)],
            "warnings": [],
        }
