"""Claude Code SDK 会话路由。

基于 ``claude-agent-sdk`` 的 ``ClaudeSDKClient`` 暴露 REST + SSE：

- ``POST   /api/claude-code/sessions``                 新建 SDK 会话
- ``GET    /api/claude-code/sessions``                 列出会话
- ``POST   /api/claude-code/sessions/{id}/messages``    发送一轮消息，SSE 回流 SDK 事件
- ``POST   /api/claude-code/sessions/{id}/permissions`` HITL 权限请求决策回传
- ``POST   /api/claude-code/sessions/{id}/interrupt``   打断当前推理
- ``DELETE /api/claude-code/sessions/{id}``            关闭并移除会话
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
