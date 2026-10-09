"""A rebuilt workbench gets a new resource identity, without changing open views."""

import asyncio
import hashlib

from fastapi import FastAPI
from mcp.shared.memory import create_connected_server_and_client_session

from src.server.workbench import mcp_server


def test_rebuilt_ui_changes_resource_identity_and_keeps_open_resource_immutable(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "FRONTEND_DIST", tmp_path)
    html = tmp_path / "index.html"
    original = "<html><body>original workbench</body></html>"
    updated = "<html><body>updated workbench</body></html>"
    html.write_text(original, encoding="utf-8")

    async def resource_uri(session):
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        uri = tools["open_workbench"].meta["ui"]["resourceUri"]
        resources = (await session.list_resources()).resources
        assert len(resources) == 1 and str(resources[0].uri) == uri
        return uri

    async def run():
        async with create_connected_server_and_client_session(mcp_server.create_server(FastAPI())) as first:
            original_uri = await resource_uri(first)
            assert hashlib.sha256(original.encode()).hexdigest() in original_uri
            async with create_connected_server_and_client_session(mcp_server.create_server(FastAPI())) as same:
                assert await resource_uri(same) == original_uri
            html.write_text(updated, encoding="utf-8")
            assert (await first.read_resource(original_uri)).contents[0].text == original
            async with create_connected_server_and_client_session(mcp_server.create_server(FastAPI())) as rebuilt:
                updated_uri = await resource_uri(rebuilt)
                assert updated_uri != original_uri
                assert (await rebuilt.read_resource(updated_uri)).contents[0].text == updated
                assert not (await rebuilt.call_tool("open_workbench", {})).isError

    asyncio.run(run())
