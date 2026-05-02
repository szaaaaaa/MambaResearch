"""Claude Code 会话只读路由（plan 2026-05-01-cli-pty-pivot Task 6a）。

经 Task 6 删除 SDK 集成后，本路由只负责"会话列表 popover"用的最小 CRUD：

- ``GET    /api/claude-code/sessions``                 列出 DB 里所有 session
- ``GET    /api/claude-code/sessions/{id}/messages``   拉 session 历史事件流（前端
  hydrate 用——PTY 模式下其实不再用，但为兼容保留）
- ``PATCH  /api/claude-code/sessions/{id}``            重命名 title
- ``DELETE /api/claude-code/sessions/{id}``            删除 session + 级联消息

实时聊天走 ``WS /api/terminal/claude``（``routes/terminal.py``），与本路由独立。
不再有 ``POST /sessions`` / ``send_message`` / ``permissions`` / ``interrupt`` /
``command`` / ``mcp`` / ``models`` 等端点——CLI 自身处理这些。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.server.claude_code.storage import ClaudeCodeStore, StoredMessage, StoredSession
from src.server.settings import ROOT

router = APIRouter()
logger = logging.getLogger(__name__)

# DB 路径——与原 session_manager 一致，保留旧 session 历史可读
_DB_PATH = ROOT / ".tmp" / "claude_code" / "sessions.db"
_store: ClaudeCodeStore | None = None


def _get_store() -> ClaudeCodeStore:
    """惰性建库连接——首次访问时创建，后续复用。"""
    global _store
    if _store is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _store = ClaudeCodeStore(_DB_PATH)
    return _store


def _session_to_row(s: StoredSession) -> dict[str, Any]:
    """ClaudeCodeSessionRow 形状（与前端 ``types.ts`` 对齐）。"""
    return {
        "id": s.id,
        "title": s.title,
        "cwd": s.cwd,
        "model": s.model,
        "permission_mode": s.permission_mode,
        "add_dirs": s.add_dirs,
        "provider": s.provider,
        "created_at": s.created_at,
        "last_message_at": s.last_message_at,
        "message_count": s.message_count,
        "total_input_tokens": s.total_input_tokens,
        "total_output_tokens": s.total_output_tokens,
        "total_cost_usd": s.total_cost_usd,
        # 旧 SDK 路径会标记 in-memory 会话为 running；PTY 模式没有这个概念
        "is_running": False,
    }


def _message_to_row(m: StoredMessage) -> dict[str, Any]:
    return {
        "sequence": m.sequence,
        "event_type": m.event_type,
        "payload": m.payload,
        "created_at": m.created_at,
    }


@router.get("/api/claude-code/sessions")
def list_sessions() -> dict[str, list[dict[str, Any]]]:
    """列出所有 Claude session（按 last_message_at DESC）。"""
    store = _get_store()
    return {"sessions": [_session_to_row(s) for s in store.list_sessions()]}


@router.get("/api/claude-code/sessions/{session_id}/messages")
def get_session_messages(session_id: str) -> dict[str, Any]:
    """返回 session 完整事件流——前端历史 hydrate 用（PTY 模式下其实只用 session 列表）。"""
    store = _get_store()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    messages = store.get_messages(session_id)
    return {
        "session": _session_to_row(session),
        "messages": [_message_to_row(m) for m in messages],
    }


@router.patch("/api/claude-code/sessions/{session_id}")
async def patch_session(session_id: str, request: Request) -> dict[str, Any]:
    """更新 title——SessionsPanel 重命名。其他字段（model / permission_mode）不再
    可改：CLI 自管它们，没有中间层。"""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    store = _get_store()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if "title" in payload:
        title_raw = payload.get("title")
        title = (
            title_raw.strip()
            if isinstance(title_raw, str) and title_raw.strip()
            else None
        )
        store.update_title(session_id, title)
        session = store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=500, detail="session vanished after update")
    return _session_to_row(session)


@router.delete("/api/claude-code/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, str]:
    """删除 session 行（messages 通过 ON DELETE CASCADE 一并清理）。"""
    store = _get_store()
    deleted = store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")
    return {"status": "deleted"}
