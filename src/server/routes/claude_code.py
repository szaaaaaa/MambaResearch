"""Claude Code SDK 会话路由。

基于 ``claude-agent-sdk`` 的 ``ClaudeSDKClient`` 暴露 REST + SSE：

- ``POST   /api/claude-code/sessions``                 新建 SDK 会话
- ``GET    /api/claude-code/sessions``                 列出会话
- ``PATCH  /api/claude-code/sessions/{id}``            更新 model / permission_mode
- ``GET    /api/claude-code/sessions/{id}/mcp``        查询挂载的 MCP server 状态
- ``POST   /api/claude-code/sessions/{id}/messages``    发送一轮消息，SSE 回流 SDK 事件
- ``POST   /api/claude-code/sessions/{id}/permissions`` HITL 权限请求决策回传
- ``POST   /api/claude-code/sessions/{id}/interrupt``   打断当前推理
- ``POST   /api/claude-code/sessions/{id}/command``     会话生命周期命令（clear/exit/add-dir）
- ``DELETE /api/claude-code/sessions/{id}``            关闭并移除会话
- ``GET    /api/claude-code/models``                   列出可选 Claude 模型
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.server.claude_code import serialize_message
from src.server.claude_code.session_manager import VALID_PERMISSION_MODES, session_manager
from src.server.settings import ROOT

router = APIRouter()


# 可选模型清单：id 直接用 SDK 接受的字符串；label 面向用户展示。
# 新增模型时在这里扩一行即可——无需改 session_manager / SDK 侧。
AVAILABLE_MODELS: list[dict[str, str]] = [
    {"id": "claude-opus-4-7", "label": "Claude Opus 4.7"},
    {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6"},
    {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5"},
]


def _sse_frame(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _resolve_cwd(cwd_raw: str | None) -> str:
    """将入参 cwd 解析到项目根下的绝对路径，防止本地 HTTP 被滥用于任意目录。"""
    cwd = (cwd_raw or "").strip() or str(ROOT)
    if not os.path.isdir(cwd):
        raise HTTPException(status_code=400, detail=f"cwd does not exist: {cwd}")
    root_resolved = pathlib.Path(ROOT).resolve()
    cwd_resolved = pathlib.Path(cwd).resolve()
    try:
        cwd_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"cwd must be within project root ({root_resolved}): {cwd}",
        ) from exc
    return str(cwd_resolved)


async def _parse_json_body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return payload


@router.post("/api/claude-code/sessions")
async def create_session(request: Request):
    payload = await _parse_json_body(request)
    cwd = _resolve_cwd(payload.get("cwd"))
    model_raw = payload.get("model")
    model = str(model_raw).strip() if isinstance(model_raw, str) and model_raw.strip() else None
    mode_raw = payload.get("permission_mode")
    permission_mode = (
        str(mode_raw).strip() if isinstance(mode_raw, str) and mode_raw.strip() else "default"
    )
    if permission_mode not in VALID_PERMISSION_MODES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"invalid permission_mode: {permission_mode!r} "
                f"(must be one of {sorted(VALID_PERMISSION_MODES)})"
            ),
        )

    try:
        session = await session_manager.create(
            cwd=cwd, model=model, permission_mode=permission_mode
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to create session: {exc}") from exc
    return session.to_dict()


@router.get("/api/claude-code/sessions")
async def list_sessions():
    return {"sessions": [s.to_dict() for s in session_manager.list_sessions()]}


@router.delete("/api/claude-code/sessions/{session_id}")
async def delete_session(session_id: str):
    deleted = await session_manager.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")
    return {"status": "deleted", "id": session_id}


@router.patch("/api/claude-code/sessions/{session_id}")
async def patch_session(session_id: str, request: Request):
    """更新会话 model / permission_mode。

    Body: ``{"model"?: str | null, "permission_mode"?: str}``

    - 两字段至少给一个；都不给 → 400
    - ``model`` 允许 ``null``，表示重置为 CLI 默认；字符串必须在 ``AVAILABLE_MODELS`` 白名单
    - ``permission_mode`` 必须是 SDK 合法值（见 ``VALID_PERMISSION_MODES``）
    - 两者都给时依次应用（model → permission_mode），任一失败后续不继续
    """
    payload = await _parse_json_body(request)
    has_model = "model" in payload
    has_mode = "permission_mode" in payload
    if not has_model and not has_mode:
        raise HTTPException(
            status_code=400,
            detail="request body must include at least one of: model, permission_mode",
        )

    # 预校验所有字段再下发，避免模型切成功后 mode 再 400 导致状态不一致
    model: str | None = None
    if has_model:
        model_raw = payload.get("model")
        if model_raw is None:
            model = None
        elif isinstance(model_raw, str) and model_raw.strip():
            model = model_raw.strip()
            allowed = {m["id"] for m in AVAILABLE_MODELS}
            if model not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"invalid model: {model!r} "
                        f"(must be one of {sorted(allowed)} or null)"
                    ),
                )
        else:
            raise HTTPException(
                status_code=400, detail="model must be a non-empty string or null"
            )

    mode: str | None = None
    if has_mode:
        mode_raw = payload.get("permission_mode")
        if not isinstance(mode_raw, str) or not mode_raw.strip():
            raise HTTPException(
                status_code=400, detail="permission_mode must be a non-empty string"
            )
        mode = mode_raw.strip()
        if mode not in VALID_PERMISSION_MODES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"invalid permission_mode: {mode!r} "
                    f"(must be one of {sorted(VALID_PERMISSION_MODES)})"
                ),
            )

    session = session_manager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    if has_model:
        session = await session_manager.switch_model(session_id, model)
        if session is None:  # 竞争下被 sweeper 回收
            raise HTTPException(status_code=404, detail="session not found")
    if has_mode:
        assert mode is not None
        session = await session_manager.switch_permission_mode(session_id, mode)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")

    assert session is not None
    return {"status": "updated", "session": session.to_dict()}


@router.get("/api/claude-code/sessions/{session_id}/mcp")
async def get_session_mcp(session_id: str):
    """查询会话挂载的 MCP server 状态。

    返回 SDK ``get_mcp_status`` 的原始响应，通常形如
    ``{"mcpServers": [{"name": "...", "status": "connected" | ...}, ...]}``，
    未挂载时 ``mcpServers`` 为空列表。
    """
    status = await session_manager.get_mcp_status(session_id)
    if status is None:
        raise HTTPException(status_code=404, detail="session not found")
    return status


@router.get("/api/claude-code/models")
async def list_models():
    """列出前端 ModelPicker 可选的 Claude 模型白名单。"""
    return {"models": list(AVAILABLE_MODELS)}


@router.post("/api/claude-code/sessions/{session_id}/permissions")
async def resolve_permission(session_id: str, request: Request):
    """前端 Modal 决策回传端点。

    Body: ``{"request_id": str, "decision": "allow"|"allow_session"|"deny", "message"?: str}``
    """
    payload = await _parse_json_body(request)
    request_id = str(payload.get("request_id", "") or "").strip()
    decision = str(payload.get("decision", "") or "").strip()
    if not request_id:
        raise HTTPException(status_code=400, detail="request_id is required")
    if decision not in ("allow", "allow_session", "deny"):
        raise HTTPException(
            status_code=400,
            detail="decision must be one of: allow, allow_session, deny",
        )

    session = session_manager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    fut = session.permission_state.pending_requests.get(request_id)
    if fut is None or fut.done():
        raise HTTPException(
            status_code=404, detail=f"no pending permission request for id {request_id}"
        )

    result: dict[str, Any] = {"decision": decision}
    message = payload.get("message")
    if isinstance(message, str) and message:
        result["message"] = message
    fut.set_result(result)
    return {"status": "ok", "request_id": request_id, "decision": decision}


@router.post("/api/claude-code/sessions/{session_id}/interrupt")
async def interrupt_session(session_id: str):
    try:
        found = await session_manager.interrupt(session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"interrupt failed: {exc}") from exc
    if not found:
        raise HTTPException(status_code=404, detail="session not found")
    return {"status": "interrupted", "id": session_id}


@router.post("/api/claude-code/sessions/{session_id}/command")
async def session_command(session_id: str, request: Request):
    """会话生命周期命令分派端点（Task 6b）。

    Body: ``{"command": "clear"|"exit"|"add-dir", "args"?: object}``

    - ``clear``: 销毁旧 SDK client 同 id 重建，清空上下文
    - ``exit``: disconnect + 从注册表移除（等价 DELETE）
    - ``add-dir``: ``args.path`` 必填，校验路径在项目根下后追加到 SDK add_dirs 并重建

    unknown command → 400；unknown session → 404。
    """
    payload = await _parse_json_body(request)
    command = str(payload.get("command", "") or "").strip().lower()
    if not command:
        raise HTTPException(status_code=400, detail="command is required")
    args_raw = payload.get("args")
    args: dict[str, Any] = args_raw if isinstance(args_raw, dict) else {}

    if command == "clear":
        session = await session_manager.clear_context(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return {"status": "cleared", "session": session.to_dict()}

    if command == "exit":
        deleted = await session_manager.delete(session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="session not found")
        return {"status": "exited", "id": session_id}

    if command == "add-dir":
        path_raw = args.get("path")
        if not isinstance(path_raw, str) or not path_raw.strip():
            raise HTTPException(
                status_code=400, detail="args.path is required for add-dir"
            )
        # 复用 create 路由的路径校验：存在 + 在项目根下
        resolved = _resolve_cwd(path_raw.strip())
        session = await session_manager.add_directory(session_id, resolved)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return {"status": "added", "session": session.to_dict()}

    raise HTTPException(
        status_code=400,
        detail=f"unknown command: {command!r} (must be one of: clear, exit, add-dir)",
    )


@router.post("/api/claude-code/sessions/{session_id}/messages")
async def send_message(session_id: str, request: Request):
    payload = await _parse_json_body(request)
    prompt = str(payload.get("prompt", "") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    # 原子 lookup + 刷新 last_activity_at，避免与 sweeper 抢占：
    # 若 touch 返回非 None，session 的时间戳已刷新到"刚才"，下一轮 sweeper
    # 扫描不会把它判定为 idle；本轮内后续调用都持有同一个 session 引用。
    session = session_manager.touch(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _emit(event: str, data: dict[str, Any]) -> None:
        """can_use_tool 桥把权限请求帧推到当前轮的 SSE 队列。"""
        queue.put_nowait(_sse_frame(event, data))

    async def _run_turn() -> None:
        # 同一会话的 query/receive_response 不能交错，用会话锁串行化
        async with session.lock:
            # 绑定本轮 SSE 发射器——can_use_tool 桥通过它推 cc_permission_request 帧
            session.permission_state.current_sse_emitter = _emit
            try:
                await session.client.query(prompt)
                async for message in session.client.receive_response():
                    try:
                        payload_dict = serialize_message(message)
                    except Exception as exc:  # 序列化失败不能让连接挂住
                        payload_dict = {"type": "error", "message": f"serialize failed: {exc}"}
                    queue.put_nowait(_sse_frame("cc_message", payload_dict))
            except Exception as exc:
                queue.put_nowait(_sse_frame("cc_error", {"message": str(exc)}))
            finally:
                session.permission_state.current_sse_emitter = None
                queue.put_nowait(_sse_frame("cc_finished", {"session_id": session.id}))
                queue.put_nowait(None)

    turn_task = asyncio.create_task(_run_turn())

    async def generate_output():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not turn_task.done():
                turn_task.cancel()
                try:
                    await turn_task
                except (asyncio.CancelledError, Exception):
                    pass

    return StreamingResponse(
        generate_output(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
