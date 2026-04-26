"""Hybrid Master Transcript：MambaResearch 拥有的 conversation messages 真相源。

设计要点
--------
- 一条 message = 一段对话原子（user 输入 / assistant 回复 / system 标记）
- ``served_by`` 区分谁产出（claude / codex / user / system / mambaresearch_compact）
- ``tool_use_summary`` 仅在跨 backend 切换时由前端文本化产生；同 backend 内为 NULL
- ``raw_payload`` 保留原始 SSE payload JSON 字符串，便于 debug 与未来升级
- ``compacted=1`` 标记此 message 已被 v3.2 auto-compact 的 rolling summary 替代——序列化
  prior history 时跳过它（用对应的 mambaresearch_compact 段代替）

切换 backend 时由 ``handleBackendSwitch`` 调 ``GET /api/conversations/{id}/messages``
拉全量，前端序列化成 prior-history 文本块作为新 backend session 的首条消息。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Literal

from src.server.projects.db import MambaDb, get_db


# 允许的 role / served_by 取值——schema CHECK 已强制，这里给类型层一份用作静态约束
Role = Literal["user", "assistant", "system"]
ServedBy = Literal["claude", "codex", "user", "system", "mambaresearch_compact"]


@dataclass
class Message:
    """单条对话消息。"""

    id: str
    conversation_id: str
    role: str
    text: str
    served_by: str
    tool_use_summary: str | None
    raw_payload: str | None
    compacted: bool
    created_at: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "text": self.text,
            "served_by": self.served_by,
            "tool_use_summary": self.tool_use_summary,
            "raw_payload": self.raw_payload,
            "compacted": self.compacted,
            "created_at": self.created_at,
        }


def _db() -> MambaDb:
    return get_db()


def append_message(
    *,
    conversation_id: str,
    role: Role,
    text: str,
    served_by: ServedBy,
    tool_use_summary: str | None = None,
    raw_payload: str | None = None,
) -> Message:
    """追加一条消息。返回完整 ``Message``（含新分配的 id 和 created_at）。

    Parameters
    ----------
    conversation_id : str
        所属 conversation。**不**校验 conversation 是否存在——上层路由保证。
    role : str
        ``user`` / ``assistant`` / ``system``。
    text : str
        消息正文。assistant 可能含 markdown；system 通常是 segment_boundary 标记
        或 mambaresearch_compact 的 rolling summary。
    served_by : str
        谁产出。``user`` 表示用户输入；``claude`` / ``codex`` 表示对应 backend；
        ``system`` 表示 MambaResearch 自身的标记；``mambaresearch_compact`` 表示
        v3.2 auto-compact 产物。
    tool_use_summary, raw_payload : str or None
        可选辅助字段——见模块文档。

    Returns
    -------
    Message
        刚 append 的完整记录（id 由本函数生成）。
    """
    now = int(time.time())
    msg = Message(
        id=uuid.uuid4().hex,
        conversation_id=conversation_id,
        role=role,
        text=text,
        served_by=served_by,
        tool_use_summary=tool_use_summary,
        raw_payload=raw_payload,
        compacted=False,
        created_at=now,
    )
    with _db().cursor() as cur:
        cur.execute(
            """
            INSERT INTO messages (
                id, conversation_id, role, text, served_by,
                tool_use_summary, raw_payload, compacted, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                msg.id,
                msg.conversation_id,
                msg.role,
                msg.text,
                msg.served_by,
                msg.tool_use_summary,
                msg.raw_payload,
                msg.created_at,
            ),
        )
    return msg


def list_by_conversation(conversation_id: str) -> list[Message]:
    """按 created_at 升序列出指定 conversation 的全部 messages。"""
    with _db().cursor() as cur:
        cur.execute(
            """
            SELECT id, conversation_id, role, text, served_by,
                   tool_use_summary, raw_payload, compacted, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (conversation_id,),
        )
        rows = cur.fetchall()
    return [_row_to_message(row) for row in rows]


def count_by_conversation(conversation_id: str) -> int:
    """统计指定 conversation 的消息数（含 compacted 标记的）。"""
    with _db().cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        (n,) = cur.fetchone()
    return int(n)


def lookup_conversation_by_session(cli_session_id: str) -> str | None:
    """从 ``cli_session_id`` 反查所属 ``conversation_id``。

    用于 SSE 路由层 (claude_code / codex routes 的 ``_run_turn``)：拿到 session_id
    后需要找到对应 conversation 才能往 messages 表写入。

    Returns
    -------
    str or None
        找到则返回 conversation_id；任何 segment 都不指向此 session 时返回 None
        （此时调用方应跳过持久化——可能是临时 / 未关联 conversation 的 session）。
    """
    with _db().cursor() as cur:
        cur.execute(
            """
            SELECT conversation_id FROM conversation_segments
            WHERE cli_session_id = ?
            ORDER BY segment_index DESC
            LIMIT 1
            """,
            (cli_session_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return str(row[0])


def _row_to_message(row) -> Message:
    return Message(
        id=str(row[0]),
        conversation_id=str(row[1]),
        role=str(row[2]),
        text=str(row[3]),
        served_by=str(row[4]),
        tool_use_summary=row[5] if row[5] is None else str(row[5]),
        raw_payload=row[6] if row[6] is None else str(row[6]),
        compacted=bool(row[7]),
        created_at=int(row[8]),
    )
