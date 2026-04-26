"""Codex app-server 会话路由（Task 5c）。

与 ``src/server/routes/claude_code.py`` 对偶——把 ``CodexSessionManager`` 暴露为
REST + SSE，形状对齐但命名空间分离（``/api/codex/*``）。

端点
----

- ``POST   /api/codex/sessions``                      新建 session（含 auth pre-flight）
- ``GET    /api/codex/sessions``                      列出内存中活跃 session
- ``GET    /api/codex/sessions/{id}``                 单条 session 详情
- ``POST   /api/codex/sessions/{id}/messages``         发送一轮消息，SSE 回流
                                                        ``codex_message`` / ``codex_finished``
                                                        / ``codex_permission_request`` 事件
- ``POST   /api/codex/sessions/{id}/permissions``      HITL 决策回传
- ``POST   /api/codex/sessions/{id}/interrupt``        打断当前 turn
- ``DELETE /api/codex/sessions/{id}``                 关闭并移除 session

设计取舍
--------

* **为什么没有 PATCH / command 端点**：Codex 侧目前不支持运行时切模型或 /clear
  语义（要换 threadId 得新建 session）；这些端点出现时机是 5d 的兼容性发现 +
  后续迭代，5c MVP 不预埋空壳。
* **为什么没有 DB store 路径**：5ba 阶段 ``CodexSessionManager`` 就没接
  ``CodexCodeStore``，list 只返回 in-memory。冷 session 恢复是后续任务——
  错过 idle TTL 的 session 现在就是 404。
* **cwd 默认项目根 + 越界校验**：与 claude_code 一致，防止本地 HTTP 被滥用。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.server.codex.session_manager import (
    VALID_SANDBOX_MODES,
    CodexAuthError,
    codex_session_manager,
)
from src.server.mcp.call_logger import McpCallContext, get_call_logger
from src.server.projects import messages_store
from src.server.projects.registry import get_registry
from src.server.settings import ROOT

router = APIRouter()
logger = logging.getLogger(__name__)


def _sse_frame(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _accumulate_codex_for_messages(
    data: dict[str, Any],
    buffer: list[str],
    conversation_id: str,
) -> None:
    """处理一帧 codex_message 用于 messages 表持久化。

    Hybrid Master Transcript T2 — Codex SSE 是 JSON-RPC notification 流，每条
    ``item/agentMessage/delta`` 是几个 token，必须本地累积。规则：

    - ``item/agentMessage/delta``：累加 delta 文本到 buffer
    - ``turn/completed``：拼接 buffer，append 一条 assistant message 到 messages 表
      （buffer 非空才写；空说明这一 turn 没生成助手文本，可能纯权限请求或错误）
    - 其他 method：忽略

    Tool use 暂不文本化进 tool_use_summary——T2 仅捕获文本；Task 4 切换路径若
    需要工具摘要可后续从 raw_payload（未存）或单独 store 派生。
    """
    method = data.get("method")
    if method == "item/agentMessage/delta":
        params = data.get("params", {})
        if isinstance(params, dict):
            delta = params.get("delta")
            if isinstance(delta, str) and delta:
                buffer.append(delta)
        return
    if method == "turn/completed":
        text = "".join(buffer)
        buffer.clear()
        if not text:
            return
        try:
            messages_store.append_message(
                conversation_id=conversation_id,
                role="assistant",
                text=text,
                served_by="codex",
                raw_payload=None,  # 完整 turn 帧序列太大，仅保留拼接后文本
            )
        except Exception:
            logger.exception("messages_store append codex assistant failed")


def _resolve_cwd(cwd_raw: str | None) -> str:
    """入参 cwd → active project 路径或其子目录；与 claude_code 共享策略。

    无 active project 时 fallback 到 ROOT（保持旧测试不破）。普通会话路径在
    ``create_session`` 入口显式拦截无 active project 的情况，给清晰 409。
    """
    active = get_registry().get_active()
    base_path = pathlib.Path(active.path) if active is not None else pathlib.Path(ROOT)
    base_resolved = base_path.resolve()
    raw = (cwd_raw or "").strip() or str(base_resolved)
    cwd_path = pathlib.Path(raw)
    if not cwd_path.is_absolute():
        cwd_path = base_resolved / cwd_path
    if not cwd_path.is_dir():
        raise HTTPException(status_code=400, detail=f"cwd does not exist: {raw}")
    cwd_resolved = cwd_path.resolve()
    try:
        cwd_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"cwd must be within active project ({base_resolved}): {raw}"
                if active is not None
                else f"cwd must be within project root ({base_resolved}): {raw}"
            ),
        ) from exc
    return str(cwd_resolved)


def _require_active_project_for_session() -> None:
    """Codex 普通会话也必须先有 active project。"""
    if get_registry().get_active() is None:
        raise HTTPException(
            status_code=409,
            detail="no active project — create or activate one before opening a session",
        )


async def _parse_json_body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400, detail="request body must be a JSON object"
        )
    return payload


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post("/api/codex/sessions")
async def create_session(request: Request):
    """新建 Codex session。

    Body: ``{cwd?: str, model?: str, sandbox_mode?: str}``

    - ``cwd`` 默认项目根；必须在项目根内
    - ``model`` 默认 ``gpt-5.5``（plan 决定 Codex 侧不做模型分档）
    - ``sandbox_mode`` 默认 ``read-only``；必须是 ``VALID_SANDBOX_MODES`` 之一

    ``~/.codex/auth.json`` 不存在或空 → 401（非 500）让前端引导用户 `codex login`。
    """
    payload = await _parse_json_body(request)

    _require_active_project_for_session()

    cwd_raw = payload.get("cwd")
    cwd = _resolve_cwd(cwd_raw if isinstance(cwd_raw, str) else None)

    model_raw = payload.get("model")
    model = (
        str(model_raw).strip()
        if isinstance(model_raw, str) and model_raw.strip()
        else None
    )

    sandbox_raw = payload.get("sandbox_mode")
    sandbox_mode = (
        str(sandbox_raw).strip()
        if isinstance(sandbox_raw, str) and sandbox_raw.strip()
        else "read-only"
    )
    if sandbox_mode not in VALID_SANDBOX_MODES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"invalid sandbox_mode: {sandbox_mode!r} "
                f"(must be one of {sorted(VALID_SANDBOX_MODES)})"
            ),
        )

    try:
        kwargs: dict[str, Any] = {"cwd": cwd, "sandbox_mode": sandbox_mode}
        if model is not None:
            kwargs["model"] = model
        session = await codex_session_manager.create(**kwargs)
    except CodexAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"failed to create session: {exc}"
        ) from exc
    return session.to_dict()


@router.get("/api/codex/sessions")
async def list_sessions():
    """列出内存中的活跃 session。

    CodexSessionManager 尚无持久化 store，所以只返回 in-memory 条目。前端
    用 ``running: True`` 表示——与 claude_code 的形状对齐但冷 session 始终
    不在此列表中（get_or_restore 也只查内存，返回 None = 404）。
    """
    return {
        "sessions": [
            {**session.to_dict(), "running": True}
            for session in codex_session_manager.list_sessions()
        ]
    }


@router.get("/api/codex/sessions/{session_id}")
async def get_session(session_id: str):
    """单条 session 详情。"""
    session = codex_session_manager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session.to_dict()


@router.delete("/api/codex/sessions/{session_id}")
async def delete_session(session_id: str):
    deleted = await codex_session_manager.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")
    return {"status": "deleted", "id": session_id}


# ---------------------------------------------------------------------------
# HITL 权限 & 中断
# ---------------------------------------------------------------------------


@router.post("/api/codex/sessions/{session_id}/permissions")
async def resolve_permission(session_id: str, request: Request):
    """前端 Modal 决策回传——与 claude_code 同样的 ``{request_id, decision}`` 形态。

    Body: ``{"request_id": str, "decision": "allow"|"allow_session"|"deny",
    "message"?: str}``
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

    session = codex_session_manager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    fut = session.permission_state.pending_requests.get(request_id)
    if fut is None or fut.done():
        raise HTTPException(
            status_code=404,
            detail=f"no pending permission request for id {request_id}",
        )

    result: dict[str, Any] = {"decision": decision}
    message = payload.get("message")
    if isinstance(message, str) and message:
        result["message"] = message
    fut.set_result(result)
    return {"status": "ok", "request_id": request_id, "decision": decision}


@router.post("/api/codex/sessions/{session_id}/interrupt")
async def interrupt_session(session_id: str):
    try:
        found = await codex_session_manager.interrupt(session_id)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"interrupt failed: {exc}"
        ) from exc
    if not found:
        raise HTTPException(status_code=404, detail="session not found")
    return {"status": "interrupted", "id": session_id}


# ---------------------------------------------------------------------------
# send_message (SSE)
# ---------------------------------------------------------------------------


@router.post("/api/codex/sessions/{session_id}/messages")
async def send_message(session_id: str, request: Request):
    """发送一轮消息并把 codex 通知流回 SSE。

    Body: ``{"prompt": str}``

    SSE 事件类型：
    - ``codex_message``: 原始 JSON-RPC notification（``item/agentMessage/delta``
      / ``turn/started`` / ``turn/completed`` 等），前端按 method 分派
    - ``codex_permission_request``: HITL 批准请求，前端弹 Modal，用户决策通过
      ``POST /permissions`` 端点回传
    - ``codex_error``: client 抛错（连接断 / RPC error）
    - ``codex_finished``: 本轮结束信号
    """
    payload = await _parse_json_body(request)
    prompt = str(payload.get("prompt", "") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    session = codex_session_manager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    session.last_activity_at = time.time()

    # Hybrid Master Transcript T2 — 把 user prompt 写入 messages 表（真相源）
    conversation_id = messages_store.lookup_conversation_by_session(session.id)
    if conversation_id is not None:
        try:
            messages_store.append_message(
                conversation_id=conversation_id,
                role="user",
                text=prompt,
                served_by="user",
            )
        except Exception:
            logger.exception("messages_store append user failed")

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    mcp_ctx = McpCallContext(cli_session_id=session.id)
    mcp_logger = get_call_logger()

    # Hybrid Master Transcript T2 — 累积 item/agentMessage/delta 进 buffer，
    # turn/completed 时一次性 append 一条 assistant message 到 messages 表。
    # Codex 的 SSE 帧是 JSON-RPC notification 流式 delta，跟 Claude 的"完整
    # message per yield"模型不同——必须本地 buffer 才能拿到完整 turn 文本。
    assistant_buffer: list[str] = []

    def _emit(event: str, data: dict[str, Any]) -> None:
        queue.put_nowait(_sse_frame(event, data))
        # Stage 3 Task 2 — MCP 调用历史观测；codex_message 是 JSON-RPC notification，
        # logger 内部按宽容策略扫整帧找 tool_use / tool_result。
        if event == "codex_message":
            try:
                mcp_logger.observe_codex_event(data, mcp_ctx)
            except Exception:
                pass
            # Hybrid MT T2 — 累积 delta；turn/completed 时落库
            if conversation_id is not None:
                _accumulate_codex_for_messages(
                    data,
                    assistant_buffer,
                    conversation_id,
                )

    async def _run_turn() -> None:
        async with session.lock:
            # 绑定本轮 SSE 发射器——permission bridge 通过它推 codex_permission_request
            session.permission_state.current_sse_emitter = _emit
            try:
                async for message in session.client.send_message(prompt):
                    _emit("codex_message", message)
            except Exception as exc:
                _emit("codex_error", {"message": str(exc)})
            finally:
                session.permission_state.current_sse_emitter = None
                _emit("codex_finished", {"session_id": session.id})
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
