"""检索网关模块 — 封装向量检索和文档索引操作。

本模块通过 MCP 网关将检索和索引请求转发给底层的 retrieval MCP 服务器。
支持两种操作：
- retrieve：基于查询语义检索已索引的文档
- index：将新文档索引到指定集合中
"""

from __future__ import annotations

from typing import Any

from src.dynamic_os.tools.gateway.mcp import McpGateway
from src.dynamic_os.tools.registry import ToolCapability


class RetrievalGateway:
    """检索网关 — 向量检索和文档索引的代理层。

    将上层的检索/索引请求封装为 MCP 调用 payload，
    通过 McpGateway 转发给 retrieval 服务器。
    """

    def __init__(self, mcp: McpGateway) -> None:
        self._mcp = mcp  # 底层 MCP 网关

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """根据查询语义检索文档。

        参数
        ----------
        query : str
            检索查询文本。
        top_k : int, optional
            最大返回文档数，默认 10。
        filters : dict, optional
            过滤条件（如 collection、run_id 等）。

        返回
        -------
        list[dict[str, Any]]
            检索到的文档列表。
        """
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
        """将文档索引到指定集合。

        参数
        ----------
        documents : list[dict]
            待索引的文档列表，每个文档应包含 text 和可选的 id/metadata。
        collection : str, optional
            目标集合名称，默认 "default"。
        """
        await self._mcp.invoke_capability(
            ToolCapability.index,
            {
                "documents": documents,
                "collection": collection,
            },
        )
