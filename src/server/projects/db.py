"""``mamba.db`` SQLite 连接 + schema migrations。

这张库是项目级"会话编排薄表"：仅记录会话头与 segment 序列，**不**存消息内容
（消息内容由 Claude/Codex CLI 自身的 JSONL 持有）。

DB 路径
~~~~~~~
- 默认 ``~/.mambaresearch/mamba.db``
- 测试可注入临时路径

并发模型
~~~~~~~~
SQLite 内置串行；Python 侧用 ``threading.Lock`` 保护连接对象，避免在多线程下
同一连接被并发使用（SQLite 默认 ``check_same_thread=True``，但本项目里
``connect()`` 时显式关闭以便 FastAPI 多线程共享）。

Migrations
~~~~~~~~~~
``MIGRATIONS`` 列表按顺序追加；启动时 ``init_db`` 读 PRAGMA ``user_version``，
跑所有大于该版本号的脚本。**追加 only**——已发布的 migration 不可修改。
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_DEFAULT_DB_PATH = Path.home() / ".mambaresearch" / "mamba.db"


# ============================================================================
# Migration 列表——按顺序排，新增只能在末尾追加
# ============================================================================
MIGRATIONS: list[str] = [
    # v1: conversations + conversation_segments
    """
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        title TEXT,
        created_at INTEGER NOT NULL,
        last_active_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_conversations_project
        ON conversations(project_id, last_active_at DESC);

    CREATE TABLE IF NOT EXISTS conversation_segments (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        segment_index INTEGER NOT NULL,
        backend TEXT NOT NULL CHECK (backend IN ('claude', 'codex')),
        cli_session_id TEXT NOT NULL,
        started_at INTEGER NOT NULL,
        ended_at INTEGER,
        handoff_prompt_path TEXT,
        UNIQUE(conversation_id, segment_index)
    );
    CREATE INDEX IF NOT EXISTS idx_segments_conv
        ON conversation_segments(conversation_id, segment_index);
    """,
    # v2: mcp_calls — Stage 3 Task 2，MCP 工具调用历史
    """
    CREATE TABLE IF NOT EXISTS mcp_calls (
        id TEXT PRIMARY KEY,
        conversation_id TEXT,           -- 可空：sandbox 直调 / 未绑会话时 NULL
        segment_id TEXT,                -- 可空：segment 还未建时 NULL
        cli_session_id TEXT,            -- 不强制——便于按 SDK session 反查
        backend TEXT NOT NULL CHECK (backend IN ('claude', 'codex', 'sandbox')),
        server_name TEXT NOT NULL,
        tool_name TEXT NOT NULL,
        tool_use_id TEXT,               -- Claude 侧 tool_use 块的 id；用于关联 tool_result
        input_json TEXT NOT NULL,       -- 调用入参 JSON 字符串
        output_json TEXT,               -- tool_result.content JSON 字符串；error 时 NULL
        is_error INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        started_at INTEGER NOT NULL,
        duration_ms INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_mcp_calls_conv
        ON mcp_calls(conversation_id, started_at DESC);
    CREATE INDEX IF NOT EXISTS idx_mcp_calls_tool
        ON mcp_calls(server_name, tool_name, started_at DESC);
    CREATE INDEX IF NOT EXISTS idx_mcp_calls_session
        ON mcp_calls(cli_session_id, started_at DESC);
    """,
    # v3: experiment_runs — Stage 4 Task 3，本地实验子进程的薄登记表
    """
    CREATE TABLE IF NOT EXISTS experiment_runs (
        id TEXT PRIMARY KEY,
        project_id TEXT,                 -- 可空：sandbox 直调 / 未关联 project
        conversation_id TEXT,
        segment_id TEXT,
        cli_session_id TEXT,
        script_path TEXT NOT NULL,
        args_json TEXT NOT NULL,         -- JSON 字符串，list[str]
        env_json TEXT,                   -- JSON 字符串，dict[str,str]，敏感字段写前已 redact
        cwd TEXT,                        -- 子进程 cwd；默认 script 所在目录
        status TEXT NOT NULL DEFAULT 'running'
            CHECK (status IN ('running', 'done', 'error', 'cancelled')),
        pid INTEGER,
        exit_code INTEGER,
        started_at INTEGER NOT NULL,
        ended_at INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_exp_runs_proj
        ON experiment_runs(project_id, started_at DESC);
    CREATE INDEX IF NOT EXISTS idx_exp_runs_session
        ON experiment_runs(cli_session_id, started_at DESC);
    """,
    # v4: messages — 原 Hybrid Master Transcript 真相源；v3.3 起降级为 read-only
    # mirror（真相源回到 backend 自己的 JSONL）。schema 不动，仅语义变更：
    # ``mambaresearch_compact`` / ``compacted`` 字段保留兼容老对话，新对话不写。
    """
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,                 -- uuid4
        conversation_id TEXT NOT NULL,
        role TEXT NOT NULL
            CHECK (role IN ('user', 'assistant', 'system')),
        text TEXT NOT NULL,                  -- 主内容（assistant 可能含 markdown）
        served_by TEXT NOT NULL
            CHECK (served_by IN (
                'claude',                    -- assistant 由 Claude backend 产出
                'codex',                     -- assistant 由 Codex backend 产出
                'user',                      -- 用户输入
                'system',                    -- segment_boundary 等系统标记
                'mambaresearch_compact'      -- v3.2 auto-compact 遗留段（兼容老对话）
            )),
        tool_use_summary TEXT,               -- mamba_history MCP tool 用作可读上下文
        raw_payload TEXT,                    -- 原始 SSE payload JSON（debug 用）
        compacted INTEGER NOT NULL DEFAULT 0,-- v3.2 auto-compact 遗留字段（兼容老对话）
        created_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_messages_conversation
        ON messages(conversation_id, created_at);
    """,
    # v5: conversation 绑定 backend（v3.3 multi-conversation 模型）
    # 每条 conversation 创建时确定 backend，永不切换。老对话默认 'claude'。
    """
    ALTER TABLE conversations
        ADD COLUMN backend TEXT NOT NULL DEFAULT 'claude'
        CHECK (backend IN ('claude', 'codex'));
    """,
    # v6: asset 标签字段（2026-04-29 asset-centric UI pivot）
    # 每条 conversation 可选关联到一个"素材"——逻辑实体，无独立表。
    # asset_kind 为 NULL 时该对话进入"草稿箱"；非 NULL 时归到对应 bucket。
    # asset_label 是用户起的素材名（如 "mamba baseline"）；同名不强制唯一。
    """
    ALTER TABLE conversations
        ADD COLUMN asset_kind TEXT
        CHECK (asset_kind IS NULL OR asset_kind IN ('experiment', 'literature', 'dataset', 'idea'));
    ALTER TABLE conversations
        ADD COLUMN asset_label TEXT;
    CREATE INDEX IF NOT EXISTS idx_conversations_asset
        ON conversations(asset_kind, last_active_at DESC);
    """,
    # v7: backend/source ID 不再由 SQLite 枚举。运行时 Registry 负责能力校验，
    # 数据库只约束非空字符串并保留历史 backend/source 值。
    """
    BEGIN IMMEDIATE;

    CREATE TABLE conversations_v7 (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        title TEXT,
        created_at INTEGER NOT NULL,
        last_active_at INTEGER NOT NULL,
        backend TEXT NOT NULL DEFAULT 'codex'
            CHECK (length(trim(backend)) > 0),
        asset_kind TEXT
            CHECK (asset_kind IS NULL OR asset_kind IN (
                'experiment', 'literature', 'dataset', 'idea'
            )),
        asset_label TEXT
    );
    INSERT INTO conversations_v7
    SELECT id, project_id, title, created_at, last_active_at,
           backend, asset_kind, asset_label
    FROM conversations;
    DROP TABLE conversations;
    ALTER TABLE conversations_v7 RENAME TO conversations;
    CREATE INDEX idx_conversations_project
        ON conversations(project_id, last_active_at DESC);
    CREATE INDEX idx_conversations_asset
        ON conversations(asset_kind, last_active_at DESC);

    CREATE TABLE conversation_segments_v7 (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        segment_index INTEGER NOT NULL,
        backend TEXT NOT NULL CHECK (length(trim(backend)) > 0),
        cli_session_id TEXT NOT NULL,
        started_at INTEGER NOT NULL,
        ended_at INTEGER,
        handoff_prompt_path TEXT,
        UNIQUE(conversation_id, segment_index)
    );
    INSERT INTO conversation_segments_v7
    SELECT id, conversation_id, segment_index, backend, cli_session_id,
           started_at, ended_at, handoff_prompt_path
    FROM conversation_segments;
    DROP TABLE conversation_segments;
    ALTER TABLE conversation_segments_v7 RENAME TO conversation_segments;
    CREATE INDEX idx_segments_conv
        ON conversation_segments(conversation_id, segment_index);

    CREATE TABLE mcp_calls_v7 (
        id TEXT PRIMARY KEY,
        conversation_id TEXT,
        segment_id TEXT,
        cli_session_id TEXT,
        backend TEXT NOT NULL CHECK (length(trim(backend)) > 0),
        server_name TEXT NOT NULL,
        tool_name TEXT NOT NULL,
        tool_use_id TEXT,
        input_json TEXT NOT NULL,
        output_json TEXT,
        is_error INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        started_at INTEGER NOT NULL,
        duration_ms INTEGER
    );
    INSERT INTO mcp_calls_v7
    SELECT id, conversation_id, segment_id, cli_session_id, backend,
           server_name, tool_name, tool_use_id, input_json, output_json,
           is_error, error, started_at, duration_ms
    FROM mcp_calls;
    DROP TABLE mcp_calls;
    ALTER TABLE mcp_calls_v7 RENAME TO mcp_calls;
    CREATE INDEX idx_mcp_calls_conv
        ON mcp_calls(conversation_id, started_at DESC);
    CREATE INDEX idx_mcp_calls_tool
        ON mcp_calls(server_name, tool_name, started_at DESC);
    CREATE INDEX idx_mcp_calls_session
        ON mcp_calls(cli_session_id, started_at DESC);

    CREATE TABLE messages_v7 (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        role TEXT NOT NULL
            CHECK (role IN ('user', 'assistant', 'system')),
        text TEXT NOT NULL,
        served_by TEXT NOT NULL CHECK (length(trim(served_by)) > 0),
        tool_use_summary TEXT,
        raw_payload TEXT,
        compacted INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    );
    INSERT INTO messages_v7
    SELECT id, conversation_id, role, text, served_by,
           tool_use_summary, raw_payload, compacted, created_at
    FROM messages;
    DROP TABLE messages;
    ALTER TABLE messages_v7 RENAME TO messages;
    CREATE INDEX idx_messages_conversation
        ON messages(conversation_id, created_at);

    COMMIT;
    """,
    # v8: recover Codex session links lost before delayed session discovery was fixed.
    """
    WITH resumable AS (
        SELECT
            c.id AS conversation_id,
            c.backend,
            c.created_at,
            c.last_active_at,
            (
                SELECT substr(
                    m.text,
                    instr(m.text, 'To continue this session, run codex resume ')
                        + length('To continue this session, run codex resume '),
                    36
                )
                FROM messages AS m
                WHERE m.conversation_id = c.id
                  AND m.role = 'assistant'
                  AND m.served_by = 'codex'
                  AND instr(
                      m.text,
                      'To continue this session, run codex resume '
                  ) > 0
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT 1
            ) AS cli_session_id
        FROM conversations AS c
        WHERE c.backend = 'codex'
          AND NOT EXISTS (
              SELECT 1
              FROM conversation_segments AS s
              WHERE s.conversation_id = c.id
          )
    )
    INSERT INTO conversation_segments (
        id, conversation_id, segment_index, backend, cli_session_id,
        started_at, ended_at, handoff_prompt_path
    )
    SELECT
        lower(hex(randomblob(16))), conversation_id, 1, backend, cli_session_id,
        created_at, last_active_at, NULL
    FROM resumable
    WHERE length(cli_session_id) = 36
      AND substr(cli_session_id, 9, 1) = '-'
      AND substr(cli_session_id, 14, 1) = '-'
      AND substr(cli_session_id, 19, 1) = '-'
      AND substr(cli_session_id, 24, 1) = '-'
      AND lower(replace(cli_session_id, '-', '')) NOT GLOB '*[^0-9a-f]*';
    """,
]


class MambaDb:
    """``mamba.db`` 的连接持有者。进程内单例，多线程共享一个连接。"""

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def connect(self) -> sqlite3.Connection:
        """获取（或建立）共享连接，确保 schema 已初始化。"""
        with self._lock:
            if self._conn is None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._conn = sqlite3.connect(
                    str(self._path),
                    check_same_thread=False,  # FastAPI 多线程共享
                    isolation_level=None,  # autocommit；显式用 cursor.executescript 控事务
                )
                self._conn.row_factory = sqlite3.Row
                # 启用 FK 与 WAL（更高并发读）
                self._conn.execute("PRAGMA foreign_keys = ON")
                self._conn.execute("PRAGMA journal_mode = WAL")
                self._init_schema(self._conn)
            return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        """读 user_version，跑所有未执行的 migration。"""
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for idx, sql in enumerate(MIGRATIONS, start=1):
            if idx <= current:
                continue
            conn.executescript(sql)
            conn.execute(f"PRAGMA user_version = {idx}")

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        """便捷上下文管理器：拿 cursor，并在退出时 commit/rollback。"""
        conn = self.connect()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


_DB_INSTANCE: MambaDb | None = None


def get_db() -> MambaDb:
    """进程级单例。"""
    global _DB_INSTANCE
    if _DB_INSTANCE is None:
        _DB_INSTANCE = MambaDb()
    return _DB_INSTANCE


def set_db_for_tests(db: MambaDb | None) -> None:
    """测试 helper。"""
    global _DB_INSTANCE
    if _DB_INSTANCE is not None:
        _DB_INSTANCE.close()
    _DB_INSTANCE = db


def init_mamba_db() -> None:
    """启动钩子：触发连接 + schema 初始化。生产 ``app.py`` 在 startup 时调用。"""
    get_db().connect()
