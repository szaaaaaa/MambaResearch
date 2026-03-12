from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.dynamic_os.tools.registry import ToolCapability, ToolDescriptor, normalize_tool_token


class McpToolConfig(BaseModel):
    model_config = {"frozen": True}

    name: str
    capability: ToolCapability
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class McpServerConfig(BaseModel):
    model_config = {"frozen": True}

    server_id: str
    tools: list[McpToolConfig] = Field(default_factory=list)


def discover_mcp_tools(servers: list[dict[str, Any]] | list[McpServerConfig]) -> list[ToolDescriptor]:
    discovered: list[ToolDescriptor] = []
    for server_payload in servers:
        server = McpServerConfig.model_validate(server_payload)
        server_id = normalize_tool_token(server.server_id)
        for tool in server.tools:
            tool_name = normalize_tool_token(tool.name)
            discovered.append(
                ToolDescriptor(
                    tool_id=f"mcp.{server_id}.{tool_name}",
                    capability=tool.capability,
                    server_id=server_id,
                    name=tool_name,
                    description=tool.description,
                    metadata=dict(tool.metadata),
                )
            )
    return discovered
