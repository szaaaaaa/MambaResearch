from __future__ import annotations

from typing import Any

from src.dynamic_os.tools.gateway.mcp import McpGateway
from src.dynamic_os.tools.registry import ToolCapability


class RetrievalGateway:
    def __init__(self, mcp: McpGateway) -> None:
        self._mcp = mcp

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        result = await self._mcp.invoke_capability(
            ToolCapability.retrieve,
            {
                "query": query,
                "top_k": top_k,
                "filters": filters or {},
            },
        )
        return list(result)

    async def index(
        self,
        documents: list[dict[str, Any]],
        *,
        collection: str = "default",
    ) -> None:
        await self._mcp.invoke_capability(
            ToolCapability.index,
            {
                "documents": documents,
                "collection": collection,
            },
        )

