"""MCP servers HTTP routes。

端点
----
- ``GET  /api/mcp/servers``                    所有 server 元信息（registry，不 ping）
- ``GET  /api/mcp/servers/{name}``             单条 server 详情
- ``GET  /api/mcp/servers/{name}/tools``       拉 server 的 tools/list（实时 probe）
- ``GET  /api/mcp/servers/status``             所有 server 的 probe 状态（并发）
- ``GET  /api/mcp/servers/{name}/status``      单 server probe 状态
- ``POST /api/mcp/sandbox/call``               sandbox 直调一个 tool

设计取舍
~~~~~~~~
- registry 与 status 分离：``GET servers`` 返回静态配置（廉价）；``GET status`` 触发
  一组 short-lived stdio probe（每个 5s 超时），相对昂贵——前端按需点
- 不暴露 restart / logs：本仓库目前无外部 server，所有 server 都是仓库内代码、由
  sandbox probe 或 Codex CLI 按需拉起；无独立的"重启"语义。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

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
from src.server.mcp.env_overrides import load_env_overrides, write_env_overrides
from src.server.mcp.probe import probe_server
from src.server.mcp.sandbox import call_tool, is_dangerous
from src.server.projects.registry import get_registry


router = APIRouter()


def _managed_providers(request: Request):
    return request.app.state.kernel.context.capabilities.mcp.list()


def _active_project_root() -> Path | None:
    active = get_registry().get_active()
    return Path(active.path) if active is not None else None


def _servers(request: Request):
    return registry.list_servers(
        _managed_providers(request),
        project_root=_active_project_root(),
    )


def _server(request: Request, name: str):
    return registry.get_server(
        name,
        _managed_providers(request),
        project_root=_active_project_root(),
    )


@router.get("/api/mcp/servers")
def list_servers(request: Request) -> dict:
    return {"servers": [s.to_dict() for s in _servers(request)]}


@router.get("/api/mcp/servers/status")
async def list_status(request: Request) -> dict:
    """并发 probe 所有 server——前端"刷新状态"按钮的入口。"""
    servers = _servers(request)
    if not servers:
        return {"statuses": []}
    statuses = await asyncio.gather(
        *[probe_server(s) for s in servers],
        return_exceptions=False,
    )
    return {"statuses": [s.to_dict() for s in statuses]}


@router.get("/api/mcp/servers/{name}")
def get_server(name: str, request: Request) -> dict:
    server = _server(request, name)
    if server is None:
        raise HTTPException(status_code=404, detail=f"MCP server not found: {name}")
    return server.to_dict()


@router.get("/api/mcp/servers/{name}/tools")
async def get_server_tools(name: str, request: Request) -> dict:
    """拉 server 的 tools 列表——通过 probe 实时取（不缓存）。"""
    server = _server(request, name)
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
async def get_server_status(name: str, request: Request) -> dict:
    server = _server(request, name)
    if server is None:
        raise HTTPException(status_code=404, detail=f"MCP server not found: {name}")
    status = await probe_server(server)
    return status.to_dict()


@router.get("/api/mcp/servers/{name}/env")
def get_server_env_override(name: str, request: Request) -> dict:
    """读指定 server 的 user env override（仅 user 层；不返回 hardcoded defaults）。"""
    server = _server(request, name)
    if server is None:
        raise HTTPException(status_code=404, detail=f"MCP server not found: {name}")
    return {"server_name": name, "env": load_env_overrides(name)}


@router.patch("/api/mcp/servers/{name}/env")
async def patch_server_env_override(name: str, request: Request) -> dict:
    """覆盖写指定 server 的 user env override。

    Body
    ----
    严格只接受 ``{"env": {key: value, ...}}`` 形状：

    * env 必须是 dict[str, str]，空 dict 表示"清空该 server 的 override"
    * 出现 ``command`` / ``args`` / ``url`` 等其他字段直接 400 拒绝——server 命令行
      定义在 Mamba-managed provider 中，禁止 user 通过 PATCH 改动（安全边界）

    ``list_servers`` 与下次 MCP 子进程启动都会解析 provider 的配置构造器并合并最新
    override。
    """
    server = _server(request, name)
    if server is None:
        raise HTTPException(status_code=404, detail=f"MCP server not found: {name}")
    payload = await _parse_json(request)
    forbidden = {"command", "args", "url", "type", "transport"} & payload.keys()
    if forbidden:
        raise HTTPException(
            status_code=400,
            detail=(
                f"fields not allowed via this endpoint: {sorted(forbidden)}. "
                "Server command/args/url are hardcoded in the Mamba-managed provider; "
                "only `env` is editable here."
            ),
        )
    extra = set(payload.keys()) - {"env"}
    if extra:
        raise HTTPException(
            status_code=400,
            detail=f"unknown fields: {sorted(extra)}. only `env` is accepted",
        )
    env = payload.get("env")
    if not isinstance(env, dict):
        raise HTTPException(
            status_code=400, detail="`env` must be a JSON object (possibly empty)"
        )
    written = write_env_overrides(name, env)
    return {"server_name": name, "env": written}


# ---------------------------------------------------------------------------
# Sandbox 直调
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

    server = _server(request, server_name)
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
# 用户自定义 server CRUD
# ---------------------------------------------------------------------------
#
# 仅支持写 ``.mcp.json``；当前 Kernel McpRegistry 中的 Mamba-managed ID 受保护。


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
        item = add_custom_server(
            payload,
            protected_server_ids=frozenset(
                provider.id for provider in _managed_providers(request)
            ),
        )
    except McpConfigForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except McpConfigConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except McpConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return item


@router.delete("/api/mcp/custom-servers/{name}")
def delete_custom(name: str, request: Request) -> dict:
    try:
        delete_custom_server(
            name,
            protected_server_ids=frozenset(
                provider.id for provider in _managed_providers(request)
            ),
        )
    except McpConfigForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except McpConfigConflict as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except McpConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "deleted", "name": name}
