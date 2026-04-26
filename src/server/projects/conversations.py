"""Conversation + ConversationSegment 的 CRUD。

设计要点
--------
- conversation 头表只记元数据（id / project_id / title / 时间戳）
- segment 记 ``(backend, cli_session_id)``，**不**存消息内容
- ``segment_index`` 是 1-based 的会话内序号；同一 conversation 内 unique
- ``ended_at`` 为空表示该 segment 是"当前活跃段"，正常情况下每个 conversation
  最多一个 active segment——切换 backend 时旧段被 close (ended_at = now) + 写新段

Stage 1 范围限制
~~~~~~~~~~~~~~~~
- 只暴露 ``create_conversation`` / ``list_by_project`` / ``delete_conversation``
  / ``get_conversation`` / ``list_segments`` / ``add_segment`` / ``close_active_segment``
- ``add_segment`` 不在路由层暴露——Stage 3 的跨 CLI 桥才会调
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from src.server.projects.db import MambaDb, get_db


@dataclass
class Conversation:
    id: str
    project_id: str
    title: str | None
    created_at: int
    last_active_at: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
        }


@dataclass
class ConversationSegment:
    id: str
    conversation_id: str
    segment_index: int
    backend: str
    cli_session_id: str
    started_at: int
    ended_at: int | None
    handoff_prompt_path: str | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "segment_index": self.segment_index,
            "backend": self.backend,
            "cli_session_id": self.cli_session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "handoff_prompt_path": self.handoff_prompt_path,
        }


def _db() -> MambaDb:
    return get_db()


def create_conversation(*, project_id: str, title: str | None = None) -> Conversation:
    now = int(time.time())
    conv = Conversation(
        id=uuid.uuid4().hex,
        project_id=project_id,
        title=title,
        created_at=now,
        last_active_at=now,
    )
    with _db().cursor() as cur:
        cur.execute(
            "INSERT INTO conversations (id, project_id, title, created_at, last_active_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (conv.id, conv.project_id, conv.title, conv.created_at, conv.last_active_at),
        )
    return conv


def list_by_project(project_id: str) -> list[Conversation]:
    with _db().cursor() as cur:
        cur.execute(
            "SELECT id, project_id, title, created_at, last_active_at "
            "FROM conversations WHERE project_id = ? "
            "ORDER BY last_active_at DESC",
            (project_id,),
        )
        rows = cur.fetchall()
    return [
        Conversation(
            id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            created_at=row["created_at"],
            last_active_at=row["last_active_at"],
        )
        for row in rows
    ]


def get_conversation(conversation_id: str) -> Conversation | None:
    with _db().cursor() as cur:
        cur.execute(
            "SELECT id, project_id, title, created_at, last_active_at "
            "FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return Conversation(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        created_at=row["created_at"],
        last_active_at=row["last_active_at"],
    )


def delete_conversation(conversation_id: str) -> bool:
    """删除会话 + 级联删 segments。返回是否真的删了一行。"""
    with _db().cursor() as cur:
        cur.execute(
            "DELETE FROM conversation_segments WHERE conversation_id = ?",
            (conversation_id,),
        )
        cur.execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,)
        )
        return cur.rowcount > 0


def update_title(conversation_id: str, title: str | None) -> bool:
    with _db().cursor() as cur:
        cur.execute(
            "UPDATE conversations SET title = ?, last_active_at = ? WHERE id = ?",
            (title, int(time.time()), conversation_id),
        )
        return cur.rowcount > 0


# ============================================================================
# Segment CRUD —— 内部使用，Stage 3 跨 CLI 桥实装时才在路由层暴露
# ============================================================================


def list_segments(conversation_id: str) -> list[ConversationSegment]:
    with _db().cursor() as cur:
        cur.execute(
            "SELECT id, conversation_id, segment_index, backend, cli_session_id, "
            "started_at, ended_at, handoff_prompt_path "
            "FROM conversation_segments WHERE conversation_id = ? "
            "ORDER BY segment_index ASC",
            (conversation_id,),
        )
        rows = cur.fetchall()
    return [
        ConversationSegment(
            id=row["id"],
            conversation_id=row["conversation_id"],
            segment_index=row["segment_index"],
            backend=row["backend"],
            cli_session_id=row["cli_session_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            handoff_prompt_path=row["handoff_prompt_path"],
        )
        for row in rows
    ]


def add_segment(
    *,
    conversation_id: str,
    backend: str,
    cli_session_id: str,
    handoff_prompt_path: str | None = None,
) -> ConversationSegment:
    """在指定会话末尾追加新 segment（segment_index 自动递增）。"""
    if backend not in ("claude", "codex"):
        raise ValueError(f"backend must be 'claude' or 'codex', got {backend!r}")
    now = int(time.time())
    seg_id = uuid.uuid4().hex
    with _db().cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(segment_index), 0) + 1 AS next_idx "
            "FROM conversation_segments WHERE conversation_id = ?",
            (conversation_id,),
        )
        next_idx = cur.fetchone()["next_idx"]
        cur.execute(
            "INSERT INTO conversation_segments "
            "(id, conversation_id, segment_index, backend, cli_session_id, "
            "started_at, ended_at, handoff_prompt_path) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
            (
                seg_id,
                conversation_id,
                next_idx,
                backend,
                cli_session_id,
                now,
                handoff_prompt_path,
            ),
        )
        cur.execute(
            "UPDATE conversations SET last_active_at = ? WHERE id = ?",
            (now, conversation_id),
        )
    return ConversationSegment(
        id=seg_id,
        conversation_id=conversation_id,
        segment_index=next_idx,
        backend=backend,
        cli_session_id=cli_session_id,
        started_at=now,
        ended_at=None,
        handoff_prompt_path=handoff_prompt_path,
    )


def close_active_segment(conversation_id: str) -> bool:
    """把指定会话当前 active 段（ended_at 为 NULL）的 ended_at 写为 now。"""
    with _db().cursor() as cur:
        cur.execute(
            "UPDATE conversation_segments SET ended_at = ? "
            "WHERE conversation_id = ? AND ended_at IS NULL",
            (int(time.time()), conversation_id),
        )
        return cur.rowcount > 0
