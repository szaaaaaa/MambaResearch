"""Conversation 跨 CLI 切换路由（Stage 3 Task 5）。

POST ``/api/conversations/{conv_id}/switch`` —— 在已有 conversation 上发起一次
backend 切换。流程：

1. 取最新 active segment（``ended_at IS NULL``）
2. 调 ``continues inspect`` 生成 handoff markdown 到 ``<project>/.mambaresearch/handoffs/<segment_id>.md``
3. 关掉旧 segment（``ended_at = now``）
4. 把 handoff 路径返回给前端，让前端：
   a. 用 target backend 的 session 创建 API 起新 SDK session（cwd 同 active project）
   b. 拿到新 cli_session_id 后调 POST ``/api/conversations/{conv_id}/segments`` 写新 segment
   c. 用 build_first_prompt(handoff_path, target_backend) 作为 first user prompt 发出去

为什么不在后端原子地完成"建 session + 写 segment"
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
现有 session 创建路径已经被 WorkbenchTab.handleCreateSession 封装得很重（含 provider
选择 / sandbox_mode / 旧 session 销毁 + 状态清理 / SSE 流接管）。在后端再封一层"创建
session"会与前端那条路径双重维护、容易漂移。最干净的拆分：后端只负责 handoff +
segment 生命周期管理；session 创建仍由前端 controller 负责。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from src.server.bridge.continues_runner import (
    HANDOFF_TTL_SEC,
    build_first_prompt,
    cleanup_expired_handoffs,
    generate_handoff,
)
from src.server.projects.conversations import (
    add_segment,
    close_active_segment,
    get_conversation,
    list_segments,
)
from src.server.projects.registry import get_registry


router = APIRouter()


def _handoffs_dir(project_path: str) -> Path:
    return Path(project_path) / ".mambaresearch" / "handoffs"


@router.post("/api/conversations/{conv_id}/switch")
async def switch_conversation_backend(conv_id: str, request: Request) -> dict:
    """在 conversation 上发起 backend 切换 + 生成 handoff。

    Body
    ----
    ``{"target_backend": "claude" | "codex"}``

    Response
    --------
    ``{
        "conversation_id": str,
        "old_segment": {...},        # 已 close 的旧 segment（含 cli_session_id 让前端可读）
        "handoff_path": str,
        "first_prompt": str,         # build_first_prompt 的产物，前端发给 target session 即可
        "used_fallback": bool,
        "fallback_error": str|None
    }``

    切换后**不写新 segment**——前端启 target backend session 拿到新 cli_session_id
    后，调 ``POST /api/conversations/{conv_id}/segments`` 写入。
    """
    payload = await _parse_json(request)
    target = str(payload.get("target_backend") or "").strip()
    if target not in ("claude", "codex"):
        raise HTTPException(
            status_code=400,
            detail="target_backend must be 'claude' or 'codex'",
        )

    conv = get_conversation(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    segments = list_segments(conv_id)
    active_segment = next((s for s in reversed(segments) if s.ended_at is None), None)
    if active_segment is None:
        raise HTTPException(
            status_code=409,
            detail="no active segment to switch from（先发起一次会话再切换）",
        )

    project = get_registry().get_active()
    if project is None:
        raise HTTPException(status_code=409, detail="no active project")

    # 清理过期 handoffs（顺手做，省得堆积）
    handoffs_dir = _handoffs_dir(project.path)
    cleanup_expired_handoffs(handoffs_dir, ttl_sec=HANDOFF_TTL_SEC)

    handoff_path = handoffs_dir / f"{active_segment.id}.md"
    result = await generate_handoff(
        cli_session_id=active_segment.cli_session_id,
        source_backend=active_segment.backend,
        target_backend=target,
        out_path=handoff_path,
    )

    close_active_segment(conv_id)

    first_prompt = build_first_prompt(result.path, target)
    return {
        "conversation_id": conv_id,
        "old_segment": active_segment.to_dict(),
        "handoff_path": str(result.path),
        "first_prompt": first_prompt,
        "used_fallback": result.used_fallback,
        "fallback_error": result.error,
    }


@router.post("/api/conversations/{conv_id}/segments")
async def append_segment(conv_id: str, request: Request) -> dict:
    """前端起完 target backend session 后，调本端点写新 segment。"""
    payload = await _parse_json(request)
    backend = str(payload.get("backend") or "").strip()
    cli_session_id = str(payload.get("cli_session_id") or "").strip()
    handoff_path = payload.get("handoff_prompt_path")

    if backend not in ("claude", "codex"):
        raise HTTPException(status_code=400, detail="backend must be 'claude' or 'codex'")
    if not cli_session_id:
        raise HTTPException(status_code=400, detail="cli_session_id is required")

    conv = get_conversation(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    seg = add_segment(
        conversation_id=conv_id,
        backend=backend,
        cli_session_id=cli_session_id,
        handoff_prompt_path=str(handoff_path) if isinstance(handoff_path, str) else None,
    )
    return seg.to_dict()


async def _parse_json(request: Request) -> dict:
    import json as _json

    try:
        payload = await request.json()
    except _json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return payload
