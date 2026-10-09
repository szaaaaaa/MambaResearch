"""MCP UI and app-only ASGI requests, without a CLI or network listener."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
from mcp import types
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.stdio import stdio_server

from src.server.projects.registry import get_registry, request_project
from src.server.projects.conversations import get_conversation
from src.server.settings import FRONTEND_DIST
from src.server.workbench.tasks import prepare_task, record_result


UI_MIME = "text/html;profile=mcp-app"


def read_ui() -> str:
    html = (FRONTEND_DIST / "index.html").read_text(encoding="utf-8")
    def inline_script(match):
        source = (FRONTEND_DIST / match[1].lstrip("/")).read_text(encoding="utf-8")
        return '<script type="module">' + source.replace("</script", "<\\/script") + "</script>"
    def inline_style(match):
        source = (FRONTEND_DIST / match[1].lstrip("/")).read_text(encoding="utf-8")
        return "<style>" + source.replace("</style", "<\\/style") + "</style>"
    html = re.sub(r'<script[^>]*src="([^"]+)"[^>]*></script>', inline_script, html)
    html = re.sub(r'<link[^>]*href="([^"]+\.css)"[^>]*>', inline_style, html)
    if re.search(r'<(?:script|link)[^>]*(?:src|href)="/assets/', html):
        raise ValueError("工作台构建包含未内联资源；请重新构建")
    return html


def create_server(application=None) -> Server:
    ui_html = read_ui()
    ui_uri = f"ui://mambaresearch/workbench-{hashlib.sha256(ui_html.encode('utf-8')).hexdigest()}.html"
    if application is None:
        from app import create_app
        application = create_app()

    @asynccontextmanager
    async def lifespan(server):
        try:
            async with application.router.lifespan_context(application):
                yield {}
        finally:
            await client.aclose()

    server = Server("mamba-workbench", version="0.1.5", lifespan=lifespan,
                    instructions="Open the research UI with open_workbench. Codex App owns execution. Record actual results only for user-panel tasks with their nonce; never launch Codex CLI.")
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://workbench")

    @server.list_tools()
    async def tools():
        def tool(name, description, properties, required, visibility=None):
            return types.Tool(name=name, description=description,
                              inputSchema={"type": "object", "properties": properties, "required": required, "additionalProperties": False},
                              _meta={"ui": visibility} if visibility else {"ui": {"resourceUri": ui_uri}})
        string = {"type": "string"}
        return [
            tool("open_workbench", "打开完整科研工作台。", {}, []),
            tool("workbench_request", "科研界面调用现有 API。", {
                "path": string, "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
                "project_id": {"type": ["string", "null"]}, "body": {"type": ["string", "null"]},
                "content_type": string,
            }, ["path", "method", "project_id"], {"visibility": ["app"]}),
            tool("prepare_task", "准备用户点击的科研任务并固定项目上下文。", {
                "project_id": string, "prompt": {"type": "string", "minLength": 1, "maxLength": 64000},
                "conversation_id": {"type": ["string", "null"]},
            }, ["project_id", "prompt"], {"visibility": ["app"]}),
            tool("record_task_result", "记录当前聊天实际完成的科研任务结果。", {
                "task_id": string, "nonce": string, "status": {"type": "string", "enum": ["completed", "error"]},
                "summary": {"type": "string", "minLength": 1}, "artifacts": {"type": "array", "items": string},
            }, ["task_id", "nonce", "status", "summary", "artifacts"], {"visibility": ["model"]}),
        ]

    @server.list_resources()
    async def resources():
        return [types.Resource(uri=ui_uri, name="MambaResearch 科研工作台", mimeType=UI_MIME)]

    @server.read_resource()
    async def resource(uri):
        if str(uri) != ui_uri:
            raise ValueError("未知工作台资源")
        return [ReadResourceContents(content=ui_html, mime_type=UI_MIME,
                    meta={"ui": {"prefersBorder": True, "permissions": {"clipboardWrite": {}}, "csp": {"connectDomains": [], "resourceDomains": []}}})]

    @server.call_tool()
    async def call(name, arguments):
        if name == "open_workbench":
            value = {"status": "ready", "execution_host": "codex_app"}
        elif name == "prepare_task":
            value = prepare_task(**arguments)
        elif name == "record_task_result":
            value = record_result(**arguments)
        elif name == "workbench_request":
            path = arguments["path"]
            split = urlsplit(path)
            decoded_path = unquote(split.path)
            if split.scheme or split.netloc or not decoded_path.startswith("/api/") or ".." in decoded_path.split("/"):
                raise ValueError("仅允许工作台内部 API 路径")
            project_id = arguments["project_id"]
            if project_id is not None:
                get_registry().get_project(project_id)
                if arguments.get("body") and (decoded_path == "/api/conversations" or arguments.get("content_type", "application/json").startswith("application/json")):
                    payload = json.loads(arguments["body"])
                    if isinstance(payload, dict) and payload.get("project_id", project_id) != project_id:
                        raise ValueError("请求体项目不匹配")
                query_ids = parse_qs(split.query, keep_blank_values=True).get("project_id", [project_id])
                if any(query_id != project_id for query_id in query_ids):
                    raise ValueError("请求项目不匹配")
                if decoded_path.startswith("/api/conversations/"):
                    conversation = get_conversation(decoded_path.split("/")[3])
                    if conversation is not None and conversation.project_id != project_id:
                        raise ValueError("研究记录不属于请求项目")
            global_routes = ("/api/projects", "/api/capabilities")
            if project_id is None and not any(decoded_path == prefix or decoded_path.startswith(prefix + "/") for prefix in global_routes):
                raise ValueError("该 API 需要明确项目 ID")
            with request_project(project_id):
                response = await client.request(arguments["method"], path, content=arguments.get("body"),
                                                headers={"content-type": arguments.get("content_type", "application/json")})
                value = {"status": response.status_code, "body": base64.b64encode(response.content).decode(), "headers": {
                    "content-type": response.headers.get("content-type", "application/octet-stream"),
                }}
        else:
            raise ValueError("未知工作台工具")
        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(value, ensure_ascii=False))], structuredContent=value)

    return server


async def main():
    server = create_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
