"""搜索网关模块 — 统一路由学术搜索和网页搜索请求。

本模块根据搜索来源（source）将请求分发到不同的 MCP 搜索服务器：
- 学术搜索（paper_search）→ 专用的论文搜索 MCP 服务器
- 网页搜索（search）→ 内部搜索 MCP 服务器（Google CSE、Bing、GitHub 等）

搜索结果会自动去重（按 paper_id / doi / url / title），并限制返回数量。
"""

from __future__ import annotations

from typing import Any

from src.dynamic_os.policy.engine import PolicyEngine
from src.dynamic_os.tools.gateway.mcp import McpGateway
from src.dynamic_os.tools.registry import ToolCapability


class SearchGateway:
    """搜索网关 — 路由搜索请求到对应的 MCP 搜索服务器。

    根据 source 参数决定调用学术搜索、网页搜索或两者兼有，
    并对多来源结果进行合并、去重和截断。
    """

    # 内部搜索服务器仅处理网页搜索；外部 MCP 处理学术搜索。
    _WEB_SERVER_ID = "search"              # 网页搜索服务器 ID
    _ACADEMIC_SERVER_ID = "paper_search"   # 学术搜索服务器 ID

    def __init__(self, *, mcp: McpGateway, policy: PolicyEngine) -> None:
        self._mcp = mcp        # MCP 网关，用于调用底层搜索工具
        self._policy = policy  # 策略引擎，用于校验网络访问权限

    async def search(
        self,
        query: str,
        *,
        source: str = "auto",
        max_results: int = 10,
    ) -> dict[str, list[dict[str, Any]] | list[str]]:
        """执行搜索并返回去重后的结果。

        参数
        ----------
        query : str
            搜索查询关键词。
        source : str, optional
            搜索来源，可选值包括 "auto"（自动）、"academic"（学术）、
            "web"（网页）、"google_cse"、"bing" 等，默认 "auto"。
        max_results : int, optional
            最大返回结果数，默认 10。

        返回
        -------
        dict
            包含 "results"（结果列表）和 "warnings"（警告列表）的字典。
        """
        # 校验网络访问权限
        self._policy.assert_network_allowed()
        search_tools = self._mcp._registry.list_by_capability(ToolCapability.search)
        if not search_tools:
            return {"results": [], "warnings": ["no search tools registered"]}

        # 根据 source 参数判断需要哪些搜索类型
        normalized = str(source or "auto").strip().lower()
        want_academic = normalized in {"", "auto", "academic", "paper", "papers"}
        want_web = normalized in {"", "auto", "web", "google_cse", "bing", "github", "duckduckgo"}

        all_results: list[dict[str, Any]] = []
        all_warnings: list[str] = []

        # 遍历所有搜索工具，按来源过滤后逐个调用
        for tool in search_tools:
            if tool.server_id == self._ACADEMIC_SERVER_ID and not want_academic:
                continue
            if tool.server_id == self._WEB_SERVER_ID and not want_web:
                continue
            try:
                result = await self._mcp.invoke_tool(
                    tool.tool_id,
                    {"query": query, "source": source, "max_results": max_results},
                )
            except Exception as exc:
                # 单个搜索源失败不中断整体搜索，记录警告
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

        # 去重并截断到 max_results
        deduped = _dedupe_results(all_results)[:max_results]
        return {"results": deduped, "warnings": all_warnings}


def _dedupe_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对搜索结果按唯一标识去重。

    按 paper_id → doi → url → title 的优先级选取去重键。

    参数
    ----------
    results : list[dict]
        原始搜索结果列表。

    返回
    -------
    list[dict]
        去重后的结果列表（保持原始顺序）。
    """
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
