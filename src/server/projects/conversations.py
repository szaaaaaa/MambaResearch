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
    backend: str
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


def _db() -> MambaDb:
    return get_db()


def create_conversation(
    *,
    project_id: str,
    title: str | None = None,
    backend: str,
    asset_kind: str | None = None,
    asset_label: str | None = None,
) -> Conversation:
    if not isinstance(backend, str) or not backend.strip():
        raise ValueError("backend must be a non-empty string")
    if asset_kind is not None and asset_kind not in VALID_ASSET_KINDS:
        raise ValueError(
            f"asset_kind must be one of {VALID_ASSET_KINDS} or None, got {asset_kind!r}"
        )
    now = int(time.time())
    conv = Conversation(
        id=uuid.uuid4().hex,
        project_id=project_id,
        title=title,
        backend=backend.strip(),
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
    """删除研究记录及关联归档。返回是否真的删了一行。"""
    with _db().cursor() as cur:
        cur.execute(
            "DELETE FROM conversation_session_archive WHERE conversation_id = ?",
            (conversation_id,),
        )
        cur.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        cur.execute("DELETE FROM workbench_tasks WHERE conversation_id = ?", (conversation_id,))
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
