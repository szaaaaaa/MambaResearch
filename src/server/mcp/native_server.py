"""Codex App research tool transport with per-request project selection."""

import argparse
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.client.stdio import stdio_client

from src.server.kernel.loader import load_kernel
from src.server.plugins.catalog import builtin_plugins
from src.server.projects.registry import get_registry
from src.server.projects.conversations import get_conversation
from src.server.projects.db import get_db


ROOT = Path(__file__).resolve().parents[3]


def create_server(server_id: str):
    kernel = load_kernel(profile_path=ROOT / "configs/plugins.json", catalog=builtin_plugins())
    provider = kernel.context.capabilities.mcp.require(server_id)
    config = provider.resolve_config()
    session = None

    @asynccontextmanager
    async def lifespan(server):
        nonlocal session
        environment = dict(config.env)
        if server_id == "mamba_zotero":
            environment.update({key: os.environ[key] for key in ("ZOTERO_USER_ID", "ZOTERO_API_KEY") if key in os.environ})
        params = StdioServerParameters(command=config.command, args=list(config.args), cwd=str(ROOT),
                                      env=environment)
        try:
            async with stdio_client(params) as streams:
                async with ClientSession(*streams) as client:
                    await client.initialize()
                    session = client
                    yield {}
        finally:
            get_db().close()

    server = Server(server_id, version="2.0.0", lifespan=lifespan,
                    instructions="Every research call requires the fixed project_id from the user's task. Codex App owns tool permissions and execution.")
    schemas = {}

    @server.list_tools()
    async def tools():
        result = await session.list_tools()
        output = []
        for original in result.tools:
            schemas[original.name] = original.inputSchema
            tool = original.model_copy(deep=True)
            tool.inputSchema.setdefault("properties", {})["project_id"] = {"type": "string", "minLength": 1, "description": "本次科研任务的注册项目 ID。"}
            tool.inputSchema["properties"].setdefault("conversation_id", {"type": ["string", "null"], "description": "关联工作台研究记录 ID，可省略。"})
            required = tool.inputSchema.setdefault("required", [])
            if "project_id" not in required:
                required.append("project_id")
            output.append(tool)
        return output

    @server.call_tool()
    async def call(name, arguments):
        project = get_registry().get_project(arguments["project_id"])
        if name not in schemas:
            await tools()
        schema = schemas.get(name)
        if schema is None:
            raise ValueError("未知科研工具")
        conversation_id = arguments.get("conversation_id")
        if conversation_id is not None:
            conversation = get_conversation(conversation_id)
            if conversation is None or conversation.project_id != project.id:
                raise ValueError("研究记录不属于任务项目")
        upstream = dict(arguments)
        if "project_id" not in schema.get("properties", {}):
            upstream.pop("project_id")
        if "conversation_id" not in schema.get("properties", {}):
            upstream.pop("conversation_id", None)
        if server_id == "mamba_workspace":
            if Path(upstream["project_path"]).resolve() != Path(project.path).resolve():
                raise ValueError("project_path 与任务项目 ID 不匹配")
        result = await session.call_tool(name, upstream)
        return result

    return server


async def main(server_id):
    server = create_server(server_id)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("server_id")
    asyncio.run(main(parser.parse_args().server_id))
