"""MambaResearch MCP visualization layer (Stage 3)。

包含 server registry / status probe / call logger / sandbox 四块。
本包仅做"读 + 探"——MCP server 的实际生命周期仍由 Claude Code SDK / Codex CLI
管理，本包不重新启动它们。

子模块：
- ``models``    — dataclass 定义（McpServerInfo / McpToolInfo / McpServerStatus）
- ``registry``  — 多 source 整合：builtin helper + .codex/config.toml + 可选 .mcp.json
- ``probe``     — stdio 短生命 subprocess ping，拉 initialize + tools/list
- ``call_logger`` — Stage 3 Task 2，把 SSE 流里的 MCP tool_use/result 落 mamba.db
- ``sandbox``   — Stage 3 Task 3，前端 GUI 直调 tool（不经过 Claude）
"""
