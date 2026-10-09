"""Real stdio protocol checks; these do not simulate a successful Codex UI test."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PLUGIN_ROOT = Path(__file__).resolve().parents[3] / "plugins" / "mamba-host-probe"


def server_parameters() -> StdioServerParameters:
    manifest = json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    config = json.loads((PLUGIN_ROOT / manifest["mcpServers"]).read_text(encoding="utf-8"))
    server = config["mcpServers"]["mamba_host_probe"]
    return StdioServerParameters(
        command=server["command"], args=server["args"], cwd=str(PLUGIN_ROOT / server["cwd"]),
    )


def test_ui_resource_and_confirmed_round_trip() -> None:
    async def run() -> None:
        params = server_parameters()
        async with stdio_client(params) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=15)) as session:
                await session.initialize()
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                uri = tools["open_probe"].meta["ui"]["resourceUri"]
                resource = (await session.read_resource(uri)).contents[0]
                assert resource.mimeType == "text/html;profile=mcp-app"
                assert "/* HOST_BRIDGE */" not in resource.text
                assert "class HostBridge" in resource.text
                assert tools["prepare_probe"].meta["ui"]["visibility"] == ["app"]
                assert tools["confirm_probe"].meta["ui"]["visibility"] == ["model"]

                opened = await session.call_tool("open_probe", {})
                probe_id = opened.structuredContent["probe_id"]
                assert opened.structuredContent["status"] == "opened"
                assert "nonce" not in json.dumps(opened.model_dump())
                prepared = await session.call_tool("prepare_probe", {
                    "probe_id": probe_id, "host_name": "protocol-test", "host_version": "1",
                    "protocol": "2026-01-26", "text_messages": True, "server_tools": True,
                })
                assert not prepared.isError
                nonce = prepared.structuredContent["message"].split("nonce=", 1)[1].split("，", 1)[0]
                for _ in range(2):
                    confirmed = await session.call_tool("confirm_probe", {"probe_id": probe_id, "nonce": nonce})
                    assert confirmed.structuredContent["status"] == "confirmed"
                state = await session.call_tool("read_probe", {"probe_id": probe_id})
                assert state.structuredContent["host_name"] == "protocol-test"
                assert "nonce" not in json.dumps(state.model_dump())

    asyncio.run(run())


def test_invalid_or_unprepared_probe_never_reports_confirmation() -> None:
    async def run() -> None:
        params = server_parameters()
        async with stdio_client(params) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=15)) as session:
                await session.initialize()
                opened = await session.call_tool("open_probe", {})
                probe_id = opened.structuredContent["probe_id"]
                premature = await session.call_tool("confirm_probe", {"probe_id": probe_id, "nonce": "a" * 32})
                assert premature.isError
                malformed = await session.call_tool("prepare_probe", {"probe_id": probe_id})
                assert malformed.isError
                missing = await session.call_tool("read_probe", {"probe_id": "00000000-0000-0000-0000-000000000000"})
                assert missing.isError
                prepared = await session.call_tool("prepare_probe", {
                    "probe_id": probe_id, "host_name": "protocol-test", "host_version": "1",
                    "protocol": "2026-01-26", "text_messages": True, "server_tools": True,
                })
                assert not prepared.isError
                invalid = await session.call_tool("confirm_probe", {"probe_id": probe_id, "nonce": "b" * 32})
                assert invalid.isError
                state = await session.call_tool("read_probe", {"probe_id": probe_id})
                assert state.structuredContent["status"] == "prepared"

    asyncio.run(run())
