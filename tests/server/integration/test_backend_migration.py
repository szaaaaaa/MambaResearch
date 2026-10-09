"""Backend/source 动态 ID migration 的集成合同测试。"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.server.projects import conversations, messages_store
from src.server.projects.db import MIGRATIONS, MambaDb, set_db_for_tests


def _build_v6_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        for migration in MIGRATIONS[:6]:
            connection.executescript(migration)
        connection.execute("PRAGMA user_version = 6")
        connection.execute("INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ("conversation-1", "project-1", "title", 1, 2, "claude", None, None))
        connection.execute("INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ("conversation-2", "project-1", "title", 3, 4, "codex", None, None))
        connection.execute("INSERT INTO conversation_segments VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ("segment-1", "conversation-1", 1, "codex", "session-1", 1, None, None))
        connection.execute("INSERT INTO mcp_calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("call-1", "conversation-1", "segment-1", "session-1", "sandbox", "server", "tool", None, "{}", None, 0, None, 1, None))
        connection.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", ("message-1", "conversation-1", "assistant", "text", "mambaresearch_compact", None, None, 0, 1))
        connection.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", ("message-2", "conversation-2", "assistant", "To continue this session, run codex resume 01a00a65-f59a-7a53-b2f3-921d5b02228e", "codex", None, None, 0, 4))
        connection.execute("INSERT INTO experiment_runs(id,project_id,script_path,args_json,status,exit_code,started_at,ended_at) VALUES ('old-run','project-1','old.py','[\"--seed\",\"7\"]','done',0,1,2)")
        connection.commit()
    finally:
        connection.close()


def test_migrations_preserve_research_records_and_archive_session_links(tmp_path: Path) -> None:
    db_path = tmp_path / "mamba.db"
    _build_v6_database(db_path)
    database = MambaDb(db_path)
    concurrent = MambaDb(db_path)
    set_db_for_tests(database)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            connection, other = list(pool.map(lambda db: db.connect(), (database, concurrent)))
        assert other.execute("PRAGMA user_version").fetchone()[0] == 10
        concurrent.close()
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 10
        assert connection.execute("SELECT backend FROM conversations").fetchone()[0] == "claude"
        assert connection.execute("SELECT backend FROM conversation_session_archive").fetchone()[0] == "codex"
        assert connection.execute("SELECT backend FROM mcp_calls").fetchone()[0] == "sandbox"
        assert connection.execute("SELECT project_id FROM mcp_calls").fetchone()[0] == "project-1"
        assert connection.execute("SELECT served_by FROM messages").fetchone()[0] == "mambaresearch_compact"
        assert tuple(connection.execute("SELECT script_path,args_json,status,exit_code,started_at,ended_at,log_count,metric_count FROM experiment_runs WHERE id='old-run'").fetchone()) == ("old.py", '["--seed","7"]', "done", 0, 1, 2, 0, 0)
        assert connection.execute("SELECT session_ref FROM conversation_session_archive WHERE conversation_id = 'conversation-2'").fetchone()[0] == "01a00a65-f59a-7a53-b2f3-921d5b02228e"
        assert {row[1] for row in connection.execute("PRAGMA index_list(messages)")} >= {"idx_messages_conversation"}

        dynamic = conversations.create_conversation(project_id="project-1", backend="test.backend")
        messages_store.append_message(conversation_id=dynamic.id, role="assistant", text="ok", served_by="test.backend")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO conversations (id, project_id, title, created_at, last_active_at, backend) VALUES (?, ?, ?, ?, ?, ?)", ("empty", "project-1", None, 1, 1, "  "))

        database.close()
        assert MambaDb(db_path).connect().execute("PRAGMA user_version").fetchone()[0] == 10
    finally:
        concurrent.close()
        set_db_for_tests(None)
