"""Conversations 与 segments 的 HTTP 路由。

端点
----
- ``GET    /api/conversations?project_id=<id>[&asset_kind=<kind|null>]``
                                                   列出指定项目的会话；可选按
                                                   asset_kind 过滤；``null`` 表示
                                                   asset_kind IS NULL（草稿箱）
- ``POST   /api/conversations``                    新建空会话
                                                   ``{project_id, title?, backend?,
                                                    asset_kind?, asset_label?}``
- ``GET    /api/conversations/{id}``               单会话详情
- ``PATCH  /api/conversations/{id}``               改 title / asset 字段
                                                   ``{title?, asset_kind?, asset_label?}``
- ``DELETE /api/conversations/{id}``               删（级联删 segments）
- ``GET    /api/conversations/{id}/segments``      列 segments
- ``POST   /api/conversations/{id}/promote-to-asset``
                                                   草稿 → 素材一键转换
                                                   ``{asset_kind, asset_label}``

**不**暴露 segment 创建端点——segment 由 Stage 3 跨 CLI 桥在 backend 内部
自动写入，前端不需要也不应该直接控制 segment 序列。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from src.server.projects.conversations import (
    DRAFTS_FILTER,
    VALID_ASSET_KINDS,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_by_project,
    list_segments,
    update_asset,
    update_title,
)
from src.server.projects.messages_store import (
    list_by_conversation as list_messages,
    lookup_conversation_by_session,
)


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
        backend=backend,
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
