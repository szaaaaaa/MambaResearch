"""Research records and preserved historical messages; no transcript mirroring."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Literal

from src.server.projects.db import MambaDb, get_db


# role 由存储层约束；served_by 是调用边界校验后的可扩展 backend ID。
Role = Literal["user", "assistant", "system"]


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
    served_by: str,
    tool_use_summary: str | None = None,
    raw_payload: str | None = None,
) -> Message:
    """追加明确保存的研究记录。"""
    if not served_by.strip():
        raise ValueError("served_by must be a non-empty string")
    now = int(time.time())
    msg = Message(
        id=uuid.uuid4().hex,
        conversation_id=conversation_id,
        role=role,
        text=text,
        served_by=served_by.strip(),
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
            ORDER BY created_at ASC, rowid ASC
            """,
            (conversation_id,),
        )
        rows = cur.fetchall()
    return [_row_to_message(row) for row in rows]


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
