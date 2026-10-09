"""MCP Apps round-trip probe; no access to Mamba or Codex user data."""

from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp import types
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.stdio import stdio_server


ROOT = Path(__file__).resolve().parent
UI_URI = "ui://mamba-host-probe/panel.html"
UI_MIME = "text/html;profile=mcp-app"
PROTOCOL = "2026-01-26"
UI_META = {"ui": {"resourceUri": UI_URI}}


def create_server() -> Server:
    server = Server(
        "mamba-host-probe",
        version="0.1.2",
        instructions=(
            "This is a development connectivity check, not the research workbench. "
            "Open its UI with open_probe. Only confirm_probe after the user sends "
            "the nonce from the panel into the current chat. Never claim that a "
            "tool-only or simulated-host test verifies Codex App rendering."
        ),
    )
    probes: dict[str, dict[str, Any]] = {}

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        probe_id = {"type": "string", "format": "uuid"}
        return [
            types.Tool(
                name="open_probe",
                description="Open the MambaResearch host connectivity panel with a fresh probe.",
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
                annotations=types.ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False),
                _meta=UI_META,
            ),
            types.Tool(
                name="prepare_probe",
                description="Record negotiated UI capabilities and prepare a user-clicked message.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "probe_id": probe_id,
                        "host_name": {"type": "string", "maxLength": 200},
                        "host_version": {"type": "string", "maxLength": 200},
                        "protocol": {"type": "string", "const": PROTOCOL},
                        "text_messages": {"type": "boolean", "const": True},
                        "server_tools": {"type": "boolean", "const": True},
                    },
                    "required": ["probe_id", "host_name", "host_version", "protocol", "text_messages", "server_tools"],
                    "additionalProperties": False,
                },
                _meta={"ui": {"visibility": ["app"]}},
            ),
            types.Tool(
                name="confirm_probe",
                description="Confirm a probe only after its nonce arrives in the user's panel message.",
                inputSchema={
                    "type": "object",
                    "properties": {"probe_id": probe_id, "nonce": {"type": "string", "minLength": 32, "maxLength": 32}},
                    "required": ["probe_id", "nonce"],
                    "additionalProperties": False,
                },
                _meta={"ui": {"visibility": ["model"]}},
            ),
            types.Tool(
                name="read_probe",
                description="Read probe state; only confirmed means a model confirmation was received.",
                inputSchema={
                    "type": "object", "properties": {"probe_id": probe_id},
                    "required": ["probe_id"], "additionalProperties": False,
                },
                annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=False),
            ),
        ]

    @server.list_resources()
    async def list_resources() -> list[types.Resource]:
        return [types.Resource(uri=UI_URI, name="MambaResearch 接入验证", mimeType=UI_MIME)]

    @server.read_resource()
    async def read_resource(uri: Any) -> list[ReadResourceContents]:
        if str(uri) != UI_URI:
            raise ValueError("Unknown UI resource")
        html = (ROOT / "ui" / "panel.html").read_text(encoding="utf-8")
        bridge = (ROOT / "ui" / "bridge.mjs").read_text(encoding="utf-8")
        html = html.replace("/* HOST_BRIDGE */", bridge.replace("export class ", "class "))
        return [ReadResourceContents(
            content=html, mime_type=UI_MIME,
            meta={"ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": []}}},
        )]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        if name == "open_probe":
            if len(probes) >= 100:
                raise ValueError("Probe limit reached; restart this development MCP server")
            probe = {"probe_id": str(uuid4()), "status": "opened", "nonce": secrets.token_hex(16)}
            probes[probe["probe_id"]] = probe
        elif name in {"prepare_probe", "confirm_probe", "read_probe"}:
            probe = probes.get(arguments["probe_id"])
            if probe is None:
                raise ValueError("Unknown probe; reopen the panel after a server restart")
            if name == "prepare_probe":
                if probe["status"] != "opened":
                    raise ValueError("Message already prepared; check the result or open a new probe")
                probe.update(
                    status="prepared", host_name=arguments["host_name"],
                    host_version=arguments["host_version"], protocol=arguments["protocol"],
                )
                prompt = (
                    "我从 MambaResearch 接入验证面板发起了此测试。请在当前聊天调用 "
                    f"mamba_host_probe 的 confirm_probe，probe_id={probe['probe_id']}，"
                    f"nonce={probe['nonce']}，并报告工具结果。这只是连接验证，不运行科研任务。"
                )
                return types.CallToolResult(content=[], structuredContent={"message": prompt})
            if name == "confirm_probe":
                if probe["status"] not in {"prepared", "confirmed"}:
                    raise ValueError("The panel has not prepared this probe")
                if not secrets.compare_digest(probe["nonce"], arguments["nonce"]):
                    raise ValueError("Incorrect probe nonce")
                probe["status"] = "confirmed"
        else:
            raise ValueError("Unknown tool")
        public = {key: value for key, value in probe.items() if key != "nonce"}
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(public, ensure_ascii=False))],
            structuredContent=public,
        )

    return server


async def main() -> None:
    server = create_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
