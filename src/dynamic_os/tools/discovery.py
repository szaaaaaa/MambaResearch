from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.dynamic_os.tools.registry import ToolCapability, ToolDescriptor, ToolRegistry, normalize_tool_token


class McpToolConfig(BaseModel):
    model_config = {"frozen": True}

    name: str
    capability: ToolCapability
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class McpServerConfig(BaseModel):
    model_config = {"frozen": True}

    server_id: str
    command: list[str] = Field(default_factory=list)
    cwd: str = ""
    env: dict[str, str] = Field(default_factory=dict)
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


@dataclass(frozen=True)
class StartedMcpRuntime:
    registry: ToolRegistry
    snapshot: list[dict[str, Any]]
    _sessions: dict[str, "_StdioMcpSession"]

    async def invoke(self, tool: ToolDescriptor, payload: dict[str, Any]) -> dict[str, Any]:
        session = self._sessions.get(tool.server_id)
        if session is None:
            raise RuntimeError(f"no MCP session for server: {tool.server_id}")
        return await session.call_tool(tool.name, payload)

    async def close(self) -> None:
        for session in self._sessions.values():
            await session.close()


class _StdioMcpSession:
    def __init__(self, *, server: McpServerConfig, root: Path) -> None:
        self._server = server
        self._root = root
        self._process: subprocess.Popen[bytes] | None = None
        self._request_id = 0
        self._io_lock = asyncio.Lock()
        self._resolved_command: list[str] = []

    @property
    def server_id(self) -> str:
        return normalize_tool_token(self._server.server_id)

    @property
    def resolved_command(self) -> list[str]:
        return list(self._resolved_command)

    async def start(self) -> None:
        if not self._server.command:
            raise RuntimeError(f"mcp server command is required for {self._server.server_id}")
        command = [self._resolve_token(token) for token in self._server.command]
        cwd = Path(self._resolve_token(self._server.cwd)).resolve() if self._server.cwd else self._root
        env = {**dict(), **{key: self._resolve_token(value) for key, value in self._server.env.items()}}
        self._process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env={**os.environ, **env},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._resolved_command = list(command)
        await self._request("initialize", {"clientInfo": {"name": "dynamic-research-os", "version": "1.0.0"}})

    async def discover_tools(self) -> list[ToolDescriptor]:
        result = await self._request("tools/list", {})
        tools = list(result.get("tools") or [])
        discovered: list[ToolDescriptor] = []
        for tool in tools:
            annotations = dict(tool.get("annotations") or {})
            metadata = dict(tool.get("metadata") or {})
            capability = annotations.get("capability") or tool.get("capability")
            tool_name = normalize_tool_token(str(tool.get("name") or ""))
            discovered.append(
                ToolDescriptor(
                    tool_id=f"mcp.{self.server_id}.{tool_name}",
                    capability=ToolCapability(capability),
                    server_id=self.server_id,
                    name=tool_name,
                    description=str(tool.get("description") or ""),
                    metadata=metadata,
                )
            )
        return discovered

    async def call_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self._request("tools/call", {"name": tool_name, "arguments": payload})
        content = result.get("structuredContent")
        if content is None:
            content = self._coerce_content(result.get("content"))
        return {
            "content": content,
            "usage": dict(result.get("usage") or {}),
        }

    async def close(self) -> None:
        if self._process is None:
            return
        process = self._process
        self._process = None
        await asyncio.to_thread(self._close_sync, process)

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._process is None:
            raise RuntimeError(f"mcp server not started: {self._server.server_id}")
        async with self._io_lock:
            self._request_id += 1
            response = await asyncio.to_thread(
                self._request_sync,
                {
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": method,
                    "params": params,
                },
            )
        if "error" in response:
            error = dict(response.get("error") or {})
            raise RuntimeError(str(error.get("message") or f"mcp {self._server.server_id} request failed"))
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"mcp {self._server.server_id} returned invalid result for {method}")
        return result

    def _request_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._process is None or self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError(f"mcp server IO unavailable: {self._server.server_id}")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        self._process.stdin.flush()
        headers: dict[str, str] = {}
        while True:
            line = self._process.stdout.readline()
            if not line:
                raise RuntimeError(f"mcp server exited during read: {self._server.server_id}")
            if line in {b"\n", b"\r\n"}:
                break
            key, _, value = line.decode("utf-8").partition(":")
            headers[key.strip().lower()] = value.strip()
        content_length = int(headers.get("content-length") or 0)
        body = self._process.stdout.read(content_length)
        if len(body) != content_length:
            raise RuntimeError(f"mcp server returned incomplete body: {self._server.server_id}")
        return json.loads(body.decode("utf-8"))

    def _resolve_token(self, value: str) -> str:
        resolved = str(value or "")
        resolved = resolved.replace("${python}", sys.executable)
        resolved = resolved.replace("${workspace_root}", str(self._root))
        return resolved

    def _coerce_content(self, value: Any) -> Any:
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
            text = value[0].get("text")
            if isinstance(text, str):
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        return value

    def _close_sync(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


async def start_mcp_runtime(
    servers: list[dict[str, Any]] | list[McpServerConfig],
    *,
    root: str | Path,
) -> StartedMcpRuntime:
    resolved_root = Path(root).resolve()
    sessions: dict[str, _StdioMcpSession] = {}
    descriptors: list[ToolDescriptor] = []
    snapshots: list[dict[str, Any]] = []
    try:
        for server_payload in servers:
            server = McpServerConfig.model_validate(server_payload)
            session = _StdioMcpSession(server=server, root=resolved_root)
            await session.start()
            sessions[session.server_id] = session
            tools = await session.discover_tools()
            descriptors.extend(tools)
            snapshots.append(
                {
                    "server_id": session.server_id,
                    "command": session.resolved_command,
                    "tools": [tool.model_dump(mode="json") for tool in tools],
                }
            )
        return StartedMcpRuntime(
            registry=ToolRegistry(descriptors),
            snapshot=snapshots,
            _sessions=sessions,
        )
    except Exception:
        for session in sessions.values():
            await session.close()
        raise
