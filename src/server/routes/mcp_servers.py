"""MCP servers HTTP routes (Stage 3 Task 1 + Task 3)。

端点
----
- ``GET  /api/mcp/servers``                    所有 server 元信息（registry，不 ping）
- ``GET  /api/mcp/servers/{name}``             单条 server 详情
- ``GET  /api/mcp/servers/{name}/tools``       拉 server 的 tools/list（实时 probe）
- ``GET  /api/mcp/servers/status``             所有 server 的 probe 状态（并发）
- ``GET  /api/mcp/servers/{name}/status``      单 server probe 状态
- ``POST /api/mcp/sandbox/call``               (Task 3) sandbox 直调一个 tool

设计取舍
~~~~~~~~
- registry 与 status 分离：``GET servers`` 返回静态配置（廉价）；``GET status`` 触发
  一组 short-lived stdio probe（每个 5s 超时），相对昂贵——前端按需点
- 不暴露 restart / logs：本仓库目前无外部 server，所有 server 都是仓库内代码、由
  Claude SDK / Codex CLI 自己拉起来；无独立的"重启"语义。后续接入用户自配 server
  时再补
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from src.server.mcp import registry
from src.server.mcp.call_logger import get_call_logger
from src.server.mcp.config_io import (
    McpConfigConflict,
    McpConfigError,
    McpConfigForbidden,
    add_custom_server,
    delete_custom_server,
    list_custom_servers,
)
from src.server.mcp.probe import probe_server
from src.server.mcp.sandbox import call_tool, is_dangerous


router = APIRouter()


@router.get("/api/mcp/servers")
def list_servers() -> dict:
    return {"servers": [s.to_dict() for s in registry.list_servers()]}


@router.get("/api/mcp/servers/status")
async def list_status() -> dict:
    """并发 probe 所有 server——前端"刷新状态"按钮的入口。"""
    servers = registry.list_servers()
    if not servers:
        return {"statuses": []}
    statuses = await asyncio.gather(
        *[probe_server(s) for s in servers],
        return_exceptions=False,
    )
    return {"statuses": [s.to_dict() for s in statuses]}


@router.get("/api/mcp/servers/{name}")
def get_server(name: str) -> dict:
    server = registry.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail=f"MCP server not found: {name}")
    return server.to_dict()


@router.get("/api/mcp/servers/{name}/tools")
async def get_server_tools(name: str) -> dict:
    """拉 server 的 tools 列表——通过 probe 实时取（不缓存）。"""
    server = registry.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail=f"MCP server not found: {name}")
    status = await probe_server(server)
    if status.status != "running":
        raise HTTPException(
            status_code=502,
            detail=f"server {name} not running: {status.error or status.status}",
        )
    return {"server_name": name, "tools": [t.to_dict() for t in status.tools]}


@router.get("/api/mcp/servers/{name}/status")
async def get_server_status(name: str) -> dict:
    server = registry.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail=f"MCP server not found: {name}")
    status = await probe_server(server)
    return status.to_dict()


# ---------------------------------------------------------------------------
# Sandbox 直调（Stage 3 Task 3）
# ---------------------------------------------------------------------------


@router.post("/api/mcp/sandbox/call")
async def sandbox_call(request: Request) -> dict:
    """直接调一个 MCP tool（不经过 Claude/Codex）——开发 server 时调试用。

    Body
    ----
    ``{"server_name": str, "tool_name": str, "input": dict, "confirm"?: bool}``

    危险 tool（``is_dangerous`` 命中）需要 ``confirm=True`` 才放行；否则返 400
    带 ``need_confirm`` 标识让前端二次提示用户。

    Response
    --------
    ``{"call_id": str, "output": ..., "is_error": bool, "error": ..., "duration_ms": int}``

    每次调用都落 ``mcp_calls`` 表（``backend='sandbox'``），与 Claude/Codex 走的
    实际调用历史并列展示，不混。
    """
    payload = await _parse_json(request)
    server_name = str(payload.get("server_name") or "").strip()
    tool_name = str(payload.get("tool_name") or "").strip()
    arguments = payload.get("input") or {}
    confirm = bool(payload.get("confirm"))

    if not server_name or not tool_name:
        raise HTTPException(
            status_code=400, detail="server_name 与 tool_name 必填"
        )
    if not isinstance(arguments, dict):
        raise HTTPException(status_code=400, detail="input 必须是 JSON 对象")

    server = registry.get_server(server_name)
    if server is None:
        raise HTTPException(
            status_code=404, detail=f"MCP server not found: {server_name}"
        )

    if is_dangerous(server_name, tool_name) and not confirm:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "need_confirm",
                "message": (
                    f"{server_name}.{tool_name} 被标记为危险工具，需要 confirm=true "
                    "才能在 sandbox 中调用。"
                ),
            },
        )

    result = await call_tool(server, tool_name, arguments)
    call_id = get_call_logger().record_sandbox_call(
        server_name=server_name,
        tool_name=tool_name,
        input_payload=arguments,
        output=result.output,
        is_error=result.is_error,
        error=result.error,
        duration_ms=result.duration_ms,
    )
    return {
        "call_id": call_id,
        "output": result.output,
        "is_error": result.is_error,
        "error": result.error,
        "duration_ms": result.duration_ms,
    }


async def _parse_json(request: Request) -> dict:
    import json as _json

    try:
        payload = await request.json()
    except _json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return payload


# ---------------------------------------------------------------------------
# 用户自定义 server CRUD（Stage 3 Task 4）
# ---------------------------------------------------------------------------
#
# 仅支持写 ``.mcp.json``——builtin helpers 与 .codex/config.toml 视为只读
# （详见 mcp/config_io.py 模块注释）。


@router.get("/api/mcp/custom-servers")
def list_custom() -> dict:
    """读 .mcp.json 里的 mcpServers 段（不含 builtin / codex toml）。"""
    return {"servers": list_custom_servers()}


@router.post("/api/mcp/custom-servers")
async def create_custom(request: Request) -> dict:
    """新增 server 到 .mcp.json。

    Body
    ----
    ``{name, transport: 'stdio'|'http'|'sse',
       command?, args?, env?, url?}``
    """
    payload = await _parse_json(request)
    try:
        item = add_custom_server(payload)
    except McpConfigForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except McpConfigConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except McpConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return item


@router.delete("/api/mcp/custom-servers/{name}")
def delete_custom(name: str) -> dict:
    try:
        delete_custom_server(name)
    except McpConfigForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except McpConfigConflict as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except McpConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "deleted", "name": name}
