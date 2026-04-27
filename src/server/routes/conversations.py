"""Conversations 与 segments 的 HTTP 路由。

Stage 1 范围
------------
仅暴露：
- ``GET    /api/conversations?project_id=<id>``    列出指定项目的会话
- ``POST   /api/conversations``                    新建空会话 ``{project_id, title?}``
- ``GET    /api/conversations/{id}``               单会话详情
- ``PATCH  /api/conversations/{id}``               改 title
- ``DELETE /api/conversations/{id}``               删（级联删 segments）
- ``GET    /api/conversations/{id}/segments``      列 segments

**不**暴露 segment 创建端点——segment 由 Stage 3 跨 CLI 桥在 backend 内部
自动写入，前端不需要也不应该直接控制 segment 序列。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from src.server.projects.conversations import (
    create_conversation,
    delete_conversation,
    get_conversation,
    list_by_project,
    list_segments,
    update_title,
)
from src.server.projects.messages_store import (
    list_by_conversation as list_messages,
    lookup_conversation_by_session,
)


router = APIRouter()


@router.get("/api/conversations")
def list_conversations(project_id: str = Query(..., min_length=1)) -> dict:
    rows = list_by_project(project_id)
    return {"conversations": [c.to_dict() for c in rows]}


@router.post("/api/conversations")
async def post_conversation(request: Request) -> dict:
    payload = await _parse_json(request)
    project_id_raw = payload.get("project_id")
    if not isinstance(project_id_raw, str) or not project_id_raw.strip():
        raise HTTPException(status_code=400, detail="project_id is required")
    title_raw = payload.get("title")
    title = title_raw.strip() if isinstance(title_raw, str) and title_raw.strip() else None
    # v3.3 multi-conversation：每条 conversation 绑定一个 backend，永不切换。
    # 入参可省（默认 'claude'），方便老客户端不报错；新前端会显式传。
    backend_raw = payload.get("backend")
    backend = backend_raw.strip() if isinstance(backend_raw, str) and backend_raw.strip() else "claude"
    if backend not in ("claude", "codex"):
        raise HTTPException(
            status_code=400, detail=f"backend must be 'claude' or 'codex', got {backend!r}"
        )
    conv = create_conversation(
        project_id=project_id_raw.strip(), title=title, backend=backend
    )
    return conv.to_dict()


@router.get("/api/conversations/{conversation_id}")
def get_one(conversation_id: str) -> dict:
    conv = get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv.to_dict()


@router.patch("/api/conversations/{conversation_id}")
async def patch_one(conversation_id: str, request: Request) -> dict:
    payload = await _parse_json(request)
    if "title" not in payload:
        raise HTTPException(status_code=400, detail="title is required")
    title_raw = payload.get("title")
    title = title_raw.strip() if isinstance(title_raw, str) and title_raw.strip() else None
    ok = update_title(conversation_id, title)
    if not ok:
        raise HTTPException(status_code=404, detail="conversation not found")
    conv = get_conversation(conversation_id)
    assert conv is not None
    return conv.to_dict()


@router.delete("/api/conversations/{conversation_id}")
def delete_one(conversation_id: str) -> dict:
    ok = delete_conversation(conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"status": "deleted", "id": conversation_id}


@router.get("/api/conversations/{conversation_id}/segments")
def list_conv_segments(conversation_id: str) -> dict:
    if get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    rows = list_segments(conversation_id)
    return {"segments": [s.to_dict() for s in rows]}


@router.get("/api/conversations/by-session/{cli_session_id}")
def get_by_session(cli_session_id: str) -> dict:
    """根据 cli_session_id 反查它所属的 conversation。

    用途（v3.3 multi-conversation）：
    - 前端切换到一条已有 codex session 时，需要找到它对应的 conversation 才能
      从 messages mirror 拉历史 hydrate UI。Codex 路径没有 SSE 事件回放端点，
      只能走 conversation mirror 这条路。
    - 找不到 → 404；找到 → 返回 ``{"conversation_id": "<id>"}``。
    """
    conv_id = lookup_conversation_by_session(cli_session_id)
    if conv_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"no conversation associated with session {cli_session_id}",
        )
    return {"conversation_id": conv_id}


@router.get("/api/conversations/{conversation_id}/messages")
def list_conv_messages(conversation_id: str) -> dict:
    """暴露 messages 表 mirror 给前端读（v3.3 multi-conversation）。

    用途：
    - WorkbenchTab mount 时 hydrate 历史（刷新页面不丢对话 UI）
    - 跨 conversation 引用（mamba_history MCP tool 内部也走同样数据）

    返回按 created_at 升序；老对话残留的 ``compacted=1`` / ``mambaresearch_compact``
    段照常返回，前端可按需展示。
    """
    if get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    msgs = list_messages(conversation_id)
    return {"messages": [m.to_dict() for m in msgs]}


async def _parse_json(request: Request) -> dict:
    import json as _json

    try:
        payload = await request.json()
    except _json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return payload
