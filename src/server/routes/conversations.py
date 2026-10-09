"""Research record metadata, assets and stored messages."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from src.server.projects.conversations import (
    DRAFTS_FILTER,
    VALID_ASSET_KINDS,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_by_project,
    update_asset,
    update_title,
)
from src.server.projects.messages_store import (
    list_by_conversation as list_messages,
)
from src.server.projects.registry import get_registry, ProjectNotFoundError


router = APIRouter()


def _coerce_asset_kind_filter(raw: str | None):
    """URL ``?asset_kind=`` 参数 → ``list_by_project`` 的 asset_kind 入参。

    - 缺省或空：None（不过滤）
    - ``"null"``（不区分大小写）：DRAFTS_FILTER（草稿）
    - 4 个 valid kind 之一：返回该字符串
    - 其他：HTTP 400
    """
    if raw is None or not raw.strip():
        return None
    s = raw.strip().lower()
    if s == "null":
        return DRAFTS_FILTER
    if s not in VALID_ASSET_KINDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"asset_kind must be one of {list(VALID_ASSET_KINDS)} or 'null', "
                f"got {raw!r}"
            ),
        )
    return s


def _validate_asset_kind_value(raw, *, allow_none: bool):
    """body ``asset_kind`` 字段校验。``allow_none=True`` 时 None 合法（用于
    PATCH 的 partial 语义）；``False`` 时 None 视为缺失。"""
    if raw is None:
        if not allow_none:
            return None
        return None
    if not isinstance(raw, str):
        raise HTTPException(
            status_code=400,
            detail="asset_kind must be string or null",
        )
    if raw not in VALID_ASSET_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"asset_kind must be one of {list(VALID_ASSET_KINDS)}",
        )
    return raw


@router.get("/api/conversations")
def list_conversations(
    project_id: str = Query(..., min_length=1),
    asset_kind: str | None = Query(default=None),
) -> dict:
    asset_filter = _coerce_asset_kind_filter(asset_kind)
    rows = list_by_project(project_id, asset_kind=asset_filter)
    return {"conversations": [c.to_dict() for c in rows]}


@router.post("/api/conversations")
async def post_conversation(request: Request) -> dict:
    payload = await _parse_json(request)
    project_id_raw = payload.get("project_id")
    if not isinstance(project_id_raw, str) or not project_id_raw.strip():
        raise HTTPException(status_code=400, detail="project_id is required")
    try:
        get_registry().get_project(project_id_raw.strip())
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    title_raw = payload.get("title")
    title = title_raw.strip() if isinstance(title_raw, str) and title_raw.strip() else None
    # 2026-04-29 asset-centric：可选 asset_kind + asset_label 一并落库
    asset_kind = _validate_asset_kind_value(payload.get("asset_kind"), allow_none=True)
    asset_label_raw = payload.get("asset_label")
    asset_label = (
        asset_label_raw.strip()
        if isinstance(asset_label_raw, str) and asset_label_raw.strip()
        else None
    )
    conv = create_conversation(
        project_id=project_id_raw.strip(),
        title=title,
        backend="codex_app",
        asset_kind=asset_kind,
        asset_label=asset_label,
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
    """部分更新。可改 ``title`` 与 asset 字段。

    body 字段语义（key 缺省 = 不动该字段）：
    - ``title``：``str`` 改名；``null`` 清空
    - ``asset_kind`` + ``asset_label``：必须**同时给**，作为一组原子更新
      （单独给一个语义不清——避免后续 dangling label）
    """
    payload = await _parse_json(request)
    has_title = "title" in payload
    has_asset = "asset_kind" in payload or "asset_label" in payload
    if not has_title and not has_asset:
        raise HTTPException(
            status_code=400,
            detail="at least one of {title, asset_kind+asset_label} is required",
        )
    if get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    if has_title:
        title_raw = payload.get("title")
        title = (
            title_raw.strip()
            if isinstance(title_raw, str) and title_raw.strip()
            else None
        )
        update_title(conversation_id, title)
    if has_asset:
        if "asset_kind" not in payload or "asset_label" not in payload:
            raise HTTPException(
                status_code=400,
                detail="asset_kind and asset_label must be provided together",
            )
        asset_kind = _validate_asset_kind_value(
            payload.get("asset_kind"), allow_none=True
        )
        asset_label_raw = payload.get("asset_label")
        asset_label = (
            asset_label_raw.strip()
            if isinstance(asset_label_raw, str) and asset_label_raw.strip()
            else None
        )
        update_asset(
            conversation_id,
            asset_kind=asset_kind,
            asset_label=asset_label,
        )
    conv = get_conversation(conversation_id)
    assert conv is not None
    return conv.to_dict()


@router.post("/api/conversations/{conversation_id}/promote-to-asset")
async def promote_to_asset(conversation_id: str, request: Request) -> dict:
    """草稿 → 素材一键转换。

    body：``{asset_kind: "experiment"|"literature"|"dataset"|"idea",
             asset_label: str (non-empty)}``

    与 PATCH 区别：promote 强制要求 asset_kind 非 NULL（不能"反向促成"），
    并且 asset_label 必须非空——这是 UI"转为素材"按钮的专用语义入口。
    """
    payload = await _parse_json(request)
    asset_kind = _validate_asset_kind_value(
        payload.get("asset_kind"), allow_none=False
    )
    if asset_kind is None:
        raise HTTPException(
            status_code=400,
            detail=f"asset_kind is required, must be one of {list(VALID_ASSET_KINDS)}",
        )
    asset_label_raw = payload.get("asset_label")
    if not isinstance(asset_label_raw, str) or not asset_label_raw.strip():
        raise HTTPException(
            status_code=400, detail="asset_label is required and must be non-empty"
        )
    if get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    update_asset(
        conversation_id,
        asset_kind=asset_kind,
        asset_label=asset_label_raw.strip(),
    )
    conv = get_conversation(conversation_id)
    assert conv is not None
    return conv.to_dict()


@router.delete("/api/conversations/{conversation_id}")
def delete_one(conversation_id: str) -> dict:
    ok = delete_conversation(conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"status": "deleted", "id": conversation_id}


@router.get("/api/conversations/{conversation_id}/messages")
def list_conv_messages(conversation_id: str) -> dict:
    """读取保存的研究记录与历史消息。"""
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
