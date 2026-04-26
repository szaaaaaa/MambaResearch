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
    conv = create_conversation(project_id=project_id_raw.strip(), title=title)
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


async def _parse_json(request: Request) -> dict:
    import json as _json

    try:
        payload = await request.json()
    except _json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return payload
