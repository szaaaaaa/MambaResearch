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


VALID_ASSET_KINDS = ("experiment", "literature", "dataset", "idea")


@dataclass
class Conversation:
    id: str
    project_id: str
    title: str | None
    backend: str  # 'claude' | 'codex'，v3.3 起绑死，永不切换
    created_at: int
    last_active_at: int
    asset_kind: str | None = None  # None 即"草稿"
    asset_label: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "backend": self.backend,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "asset_kind": self.asset_kind,
            "asset_label": self.asset_label,
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


def create_conversation(
    *,
    project_id: str,
    title: str | None = None,
    backend: str = "claude",
    asset_kind: str | None = None,
    asset_label: str | None = None,
) -> Conversation:
    if backend not in ("claude", "codex"):
        raise ValueError(f"backend must be 'claude' or 'codex', got {backend!r}")
    if asset_kind is not None and asset_kind not in VALID_ASSET_KINDS:
        raise ValueError(
            f"asset_kind must be one of {VALID_ASSET_KINDS} or None, got {asset_kind!r}"
        )
    now = int(time.time())
    conv = Conversation(
        id=uuid.uuid4().hex,
        project_id=project_id,
        title=title,
        backend=backend,
        created_at=now,
        last_active_at=now,
        asset_kind=asset_kind,
        asset_label=asset_label,
    )
    with _db().cursor() as cur:
        cur.execute(
            "INSERT INTO conversations "
            "(id, project_id, title, backend, created_at, last_active_at, "
            "asset_kind, asset_label) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conv.id,
                conv.project_id,
                conv.title,
                conv.backend,
                conv.created_at,
                conv.last_active_at,
                conv.asset_kind,
                conv.asset_label,
            ),
        )
    return conv


# 哨兵：``list_by_project(asset_kind=DRAFTS_FILTER)`` 表示 ``asset_kind IS NULL``
# （草稿）。区别于 ``asset_kind=None`` 表示"不过滤"。路由层把 URL 参数
# ``?asset_kind=null`` 翻译成本哨兵。
DRAFTS_FILTER = object()


def list_by_project(
    project_id: str,
    *,
    asset_kind: str | object | None = None,
) -> list[Conversation]:
    """列出 project 的 conversations。

    Parameters
    ----------
    project_id : str
        项目 id
    asset_kind : str | None | object
        - None：不按 asset_kind 过滤（默认）
        - VALID_ASSET_KINDS 之一：仅返回该 kind
        - ``DRAFTS_FILTER`` 哨兵：仅返回 asset_kind IS NULL（草稿）
    """
    clauses = ["project_id = ?"]
    params: list = [project_id]
    if asset_kind is DRAFTS_FILTER:
        clauses.append("asset_kind IS NULL")
    elif isinstance(asset_kind, str):
        if asset_kind not in VALID_ASSET_KINDS:
            raise ValueError(
                f"asset_kind must be one of {VALID_ASSET_KINDS} or None, got {asset_kind!r}"
            )
        clauses.append("asset_kind = ?")
        params.append(asset_kind)
    where = " AND ".join(clauses)
    with _db().cursor() as cur:
        cur.execute(
            "SELECT id, project_id, title, backend, created_at, last_active_at, "
            "asset_kind, asset_label "
            f"FROM conversations WHERE {where} "
            "ORDER BY last_active_at DESC",
            params,
        )
        rows = cur.fetchall()
    return [_row_to_conversation(row) for row in rows]


def get_conversation(conversation_id: str) -> Conversation | None:
    with _db().cursor() as cur:
        cur.execute(
            "SELECT id, project_id, title, backend, created_at, last_active_at, "
            "asset_kind, asset_label "
            "FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return _row_to_conversation(row)


def _row_to_conversation(row) -> Conversation:
    return Conversation(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        backend=row["backend"],
        created_at=row["created_at"],
        last_active_at=row["last_active_at"],
        asset_kind=row["asset_kind"],
        asset_label=row["asset_label"],
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


def update_asset(
    conversation_id: str,
    *,
    asset_kind: str | None,
    asset_label: str | None,
) -> bool:
    """改某 conversation 的 asset 标签。``asset_kind=None`` 即降回草稿。

    用于 promote-to-asset 端点 + 后续可能的"取消素材化"操作。
    """
    if asset_kind is not None and asset_kind not in VALID_ASSET_KINDS:
        raise ValueError(
            f"asset_kind must be one of {VALID_ASSET_KINDS} or None, got {asset_kind!r}"
        )
    with _db().cursor() as cur:
        cur.execute(
            "UPDATE conversations "
            "SET asset_kind = ?, asset_label = ?, last_active_at = ? "
            "WHERE id = ?",
            (asset_kind, asset_label, int(time.time()), conversation_id),
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
