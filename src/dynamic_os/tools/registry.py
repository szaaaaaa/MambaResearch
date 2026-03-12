from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def normalize_tool_token(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if not normalized:
        raise ValueError("tool token cannot be empty")
    return normalized


class ToolCapability(str, Enum):
    llm_chat = "llm_chat"
    search = "search"
    retrieve = "retrieve"
    index = "index"
    execute_code = "execute_code"
    read_file = "read_file"
    write_file = "write_file"


class ToolDescriptor(BaseModel):
    model_config = {"frozen": True}

    tool_id: str = Field(..., pattern=r"^mcp\.[a-z0-9_]+\.[a-z0-9_]+$")
    capability: ToolCapability
    server_id: str
    name: str
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolRegistry:
    def __init__(self, tools: list[ToolDescriptor]) -> None:
        self._tools = {tool.tool_id: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("tool ids must be unique")

    @classmethod
    def from_servers(cls, servers: list[dict[str, Any]] | list[Any]) -> "ToolRegistry":
        from src.dynamic_os.tools.discovery import discover_mcp_tools

        return cls(discover_mcp_tools(servers))

    def get(self, tool_id: str) -> ToolDescriptor:
        return self._tools[tool_id]

    def list(self) -> list[ToolDescriptor]:
        return [self._tools[tool_id] for tool_id in sorted(self._tools)]

    def list_by_capability(self, capability: ToolCapability | str) -> list[ToolDescriptor]:
        target = ToolCapability(capability)
        return [tool for tool in self.list() if tool.capability == target]

    def resolve(self, capability: ToolCapability | str, *, preferred: str = "auto") -> ToolDescriptor:
        candidates = self.list_by_capability(capability)
        if not candidates:
            raise ValueError(f"no tools registered for capability: {ToolCapability(capability).value}")

        if preferred in {"", "auto"}:
            return candidates[0]

        for tool in candidates:
            if tool.tool_id == preferred:
                return tool

        preferred_token = normalize_tool_token(preferred)
        for tool in candidates:
            if tool.name == preferred_token or tool.tool_id.endswith(f".{preferred_token}"):
                return tool

        raise ValueError(
            f"no tool for capability {ToolCapability(capability).value} matched preference: {preferred}"
        )
