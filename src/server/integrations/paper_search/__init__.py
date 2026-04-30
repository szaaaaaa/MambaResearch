"""paper_search.* MCP server adapter — builtin helper for academic paper search.

实际 MCP server 本体在 PyPI 包 ``paper_search_mcp`` 中（``python -m
paper_search_mcp.server`` 启动）。本模块只导出 ``default_mcp_config`` 让
``src.server.mcp.registry`` 把它注册为 builtin helper。
"""

from src.server.integrations.paper_search.mcp_server import default_mcp_config

__all__ = ["default_mcp_config"]
