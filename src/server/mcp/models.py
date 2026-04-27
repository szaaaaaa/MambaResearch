"""MCP visualization 数据模型（Stage 3 Task 1）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Transport = Literal["stdio", "http", "sse"]
SourceLabel = Literal[
    "builtin_helper",       # MambaResearch 自己的 default_mcp_config 函数注入的（programmatic）
    "codex_project",        # <repo>/.codex/config.toml
    "codex_global",         # ~/.codex/config.toml
    "mcp_json",             # .mcp.json（项目级，Claude Code 约定）
]


@dataclass
class McpServerInfo:
    """单个 MCP server 的静态配置信息——不含运行时状态。

    同一个 server name 可能出现在多个 source 里（例如 ``mamba_workspace`` 同时
    被 builtin helper 注册到 Claude SDK + 写在 .codex/config.toml 里）；registry
    按 name 去重，sources 字段累加。
    """

    name: str
    transport: Transport
    sources: list[SourceLabel] = field(default_factory=list)
    config_paths: list[str] = field(default_factory=list)
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None  # http / sse only

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "transport": self.transport,
            "sources": list(self.sources),
            "config_paths": list(self.config_paths),
            "command": self.command,
            "args": list(self.args),
            "env": dict(self.env),
            "url": self.url,
        }


@dataclass
class McpToolInfo:
    """单个 tool 元信息——直接来自 server 的 tools/list 响应。"""

    server_name: str
    name: str
    description: str | None
    input_schema: dict[str, Any]

    @property
    def qualified_name(self) -> str:
        """Claude Code SDK 在前端可见的完整 ID：``mcp__<server>__<tool>``。"""
        return f"mcp__{self.server_name}__{self.name}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "server_name": self.server_name,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class McpServerStatus:
    """Probe 结果——拉一次 initialize + tools/list 拿到的运行时状态。"""

    server_name: str
    status: Literal["running", "error", "unreachable"]
    tools_count: int
    tools: list[McpToolInfo] = field(default_factory=list)
    last_ping_at: int | None = None
    duration_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "server_name": self.server_name,
            "status": self.status,
            "tools_count": self.tools_count,
            "tools": [t.to_dict() for t in self.tools],
            "last_ping_at": self.last_ping_at,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }
