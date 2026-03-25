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
        search_tools = self._mcp._registry.list_by_capability(ToolCapability.search)
        if not search_tools:
            return {"results": [], "warnings": ["no search tools registered"]}

        all_results: list[dict[str, Any]] = []
        all_warnings: list[str] = []

        for tool in search_tools:
            try:
                result = await self._mcp.invoke_tool(
                    tool.tool_id,
                    {"query": query, "source": source, "max_results": max_results},
                )
            except Exception as exc:
                all_warnings.append(f"{tool.tool_id}: {exc}")
                continue
            if isinstance(result, dict):
                all_results.extend(
                    dict(item) for item in result.get("results", []) if isinstance(item, dict)
                )
                all_warnings.extend(
                    str(w).strip() for w in result.get("warnings", []) if str(w).strip()
                )
            elif isinstance(result, list):
                all_results.extend(dict(item) for item in result if isinstance(item, dict))

        deduped = _dedupe_results(all_results)[:max_results]
        return {"results": deduped, "warnings": all_warnings}


def _dedupe_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in results:
        key = str(
            item.get("paper_id") or item.get("doi") or item.get("url") or item.get("title") or ""
        ).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
