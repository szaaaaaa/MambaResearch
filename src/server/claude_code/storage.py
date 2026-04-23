"""Claude Code 会话 SQLite 持久化。

提供 ``ClaudeCodeStore`` 封装 sqlite3 连接，覆盖 sessions 元数据 + messages 事件
流的 CRUD。SessionManager 在以下点写库：

- ``create`` 后 ``insert_session``
- 每条 SSE 事件序列化后 ``append_message``（cc_message / cc_error / cc_permission_request / cc_finished）
- ResultMessage 到达时 ``accumulate_usage`` 累加 token / cost
- ``clear_context`` 保留 sessions 行（语义上"同 id 继续"），但 ``cascade_delete_messages``
  清空 messages——CLI resume 从零开始
- ``delete`` / idle-evict 不删 DB 记录，只断 SDK client；DB 历史为刷新恢复保留

DB 文件默认在 ``.tmp/claude_code/sessions.db``（.gitignore 已覆盖 ``.tmp/``）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    cwd TEXT NOT NULL,
    model TEXT,
    permission_mode TEXT NOT NULL,
    add_dirs_json TEXT NOT NULL DEFAULT '[]',
    provider TEXT,
    created_at REAL NOT NULL,
    last_message_at REAL NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    total_input_tokens INTEGER NOT NULL DEFAULT 0,
    total_output_tokens INTEGER NOT NULL DEFAULT 0,
    total_cost_usd REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS messages (
    session_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (session_id, sequence),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, sequence);
"""


@dataclass
class StoredSession:
    """sessions 行的 Python 表示。"""

    id: str
    title: str | None
    cwd: str
    model: str | None
    permission_mode: str
    add_dirs: list[str] = field(default_factory=list)
    provider: str | None = None
    created_at: float = 0.0
    last_message_at: float = 0.0
    message_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "cwd": self.cwd,
            "model": self.model,
            "permission_mode": self.permission_mode,
            "add_dirs": list(self.add_dirs),
            "provider": self.provider,
            "created_at": self.created_at,
            "last_message_at": self.last_message_at,
            "message_count": self.message_count,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": self.total_cost_usd,
        }


@dataclass
class StoredMessage:
    """messages 行的 Python 表示。"""

    session_id: str
    sequence: int
    event_type: str
    payload: Any
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload": self.payload,
            "created_at": self.created_at,
        }


class ClaudeCodeStore:
    """线程安全的 sqlite3 封装。所有写操作持锁串行。"""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # autocommit 模式（isolation_level=None）+ check_same_thread=False 允许跨线程调用；
        # 本类持 threading.Lock 串行化，不依赖 sqlite 自身线程亲和。
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        # 启用 FK 级联，delete_session 自动清 messages
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            # 已存在表的旧 DB 升级——provider 列是 Task 1b 新增的。ALTER TABLE 失败只可能
            # 是列已存在（"duplicate column"），其它 OperationalError 不吞。
            try:
                self._conn.execute("ALTER TABLE sessions ADD COLUMN provider TEXT")
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # sessions CRUD
    # ------------------------------------------------------------------

    def insert_session(
        self,
        *,
        session_id: str,
        cwd: str,
        model: str | None,
        permission_mode: str,
        add_dirs: list[str] | None = None,
        title: str | None = None,
        provider: str | None = None,
    ) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (
                    id, title, cwd, model, permission_mode, add_dirs_json,
                    provider, created_at, last_message_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    title,
                    cwd,
                    model,
                    permission_mode,
                    json.dumps(list(add_dirs or []), ensure_ascii=False),
                    provider,
                    now,
                    now,
                ),
            )

    def update_model(self, session_id: str, model: str | None) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE sessions SET model = ?, last_message_at = ? WHERE id = ?",
                (model, time.time(), session_id),
            )
            return cur.rowcount > 0

    def update_permission_mode(self, session_id: str, mode: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE sessions SET permission_mode = ?, last_message_at = ? WHERE id = ?",
                (mode, time.time(), session_id),
            )
            return cur.rowcount > 0

    def update_add_dirs(self, session_id: str, add_dirs: list[str]) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE sessions SET add_dirs_json = ?, last_message_at = ? WHERE id = ?",
                (json.dumps(list(add_dirs), ensure_ascii=False), time.time(), session_id),
            )
            return cur.rowcount > 0

    def update_title(self, session_id: str, title: str | None) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                (title, session_id),
            )
            return cur.rowcount > 0

    def accumulate_usage(
        self,
        session_id: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> bool:
        """累加 ResultMessage 的 usage 到 sessions 行。负值非法（不校验，调用方保证）。"""
        with self._lock:
            cur = self._conn.execute(
                """
                UPDATE sessions SET
                    total_input_tokens = total_input_tokens + ?,
                    total_output_tokens = total_output_tokens + ?,
                    total_cost_usd = total_cost_usd + ?
                WHERE id = ?
                """,
                (input_tokens, output_tokens, float(cost_usd), session_id),
            )
            return cur.rowcount > 0

    def get_session(self, session_id: str) -> StoredSession | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return _row_to_session(row) if row else None

    def list_sessions(self) -> list[StoredSession]:
        """按 last_message_at DESC 返回所有 session。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY last_message_at DESC"
            ).fetchall()
        return [_row_to_session(r) for r in rows]

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # messages append / fetch
    # ------------------------------------------------------------------

    def append_message(
        self,
        session_id: str,
        *,
        event_type: str,
        payload: Any,
    ) -> int:
        """按 session 维度自增 sequence 落一行消息，并更新 last_message_at + message_count。

        payload 必须是 JSON-serializable（通常来自 ``serialize_message`` 的 dict）。
        写入对 session 不存在时静默失败（不抛）——允许调用方在 session 已被删除
        的边缘时刻继续推事件而不崩溃；返回 sequence，若失败返回 -1。
        """
        now = time.time()
        payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        with self._lock:
            row = self._conn.execute(
                "SELECT message_count FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return -1
            sequence = int(row["message_count"])
            self._conn.execute(
                """
                INSERT INTO messages (
                    session_id, sequence, event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, sequence, event_type, payload_json, now),
            )
            self._conn.execute(
                """
                UPDATE sessions SET
                    message_count = message_count + 1,
                    last_message_at = ?
                WHERE id = ?
                """,
                (now, session_id),
            )
            return sequence

    def get_messages(
        self, session_id: str, *, limit: int | None = None, offset: int = 0
    ) -> list[StoredMessage]:
        """按 sequence ASC 返回历史消息。limit=None 表示全部。"""
        query = (
            "SELECT * FROM messages WHERE session_id = ? ORDER BY sequence ASC"
        )
        params: list[Any] = [session_id]
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([int(limit), int(offset)])
        elif offset:
            query += " LIMIT -1 OFFSET ?"
            params.append(int(offset))
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        out: list[StoredMessage] = []
        for r in rows:
            try:
                payload = json.loads(r["payload_json"])
            except json.JSONDecodeError:
                payload = None
            out.append(
                StoredMessage(
                    session_id=r["session_id"],
                    sequence=int(r["sequence"]),
                    event_type=r["event_type"],
                    payload=payload,
                    created_at=float(r["created_at"]),
                )
            )
        return out

    def clear_messages(self, session_id: str) -> int:
        """清空指定 session 的 messages + 把 message_count 归零。

        用于 ``/clear``——DB 语义与 CLI 的 "同 id 继续但上下文清空" 对齐：
        sessions 行保留，messages 清空并重置 count。注意 add_dirs / model /
        permission_mode 等 session 级配置保留。
        """
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM messages WHERE session_id = ?", (session_id,)
            )
            self._conn.execute(
                "UPDATE sessions SET message_count = 0 WHERE id = ?", (session_id,)
            )
            return cur.rowcount


def _row_to_session(row: sqlite3.Row) -> StoredSession:
    try:
        add_dirs = json.loads(row["add_dirs_json"]) or []
    except (json.JSONDecodeError, TypeError):
        add_dirs = []
    return StoredSession(
        id=row["id"],
        title=row["title"],
        cwd=row["cwd"],
        model=row["model"],
        permission_mode=row["permission_mode"],
        add_dirs=list(add_dirs),
        provider=row["provider"],
        created_at=float(row["created_at"]),
        last_message_at=float(row["last_message_at"]),
        message_count=int(row["message_count"]),
        total_input_tokens=int(row["total_input_tokens"]),
        total_output_tokens=int(row["total_output_tokens"]),
        total_cost_usd=float(row["total_cost_usd"]),
    )
