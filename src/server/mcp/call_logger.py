"""MCP sandbox call persistence."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from src.server.projects.db import MambaDb, get_db


logger = logging.getLogger(__name__)


class McpCallLogger:
    def __init__(self, db: MambaDb | None = None) -> None:
        self._db = db

    @property
    def db(self) -> MambaDb:
        return self._db or get_db()

    def record_sandbox_call(
        self,
        *,
        server_name: str,
        tool_name: str,
        input_payload: Any,
        output: Any,
        is_error: bool,
        error: str | None,
        duration_ms: int,
    ) -> str:
        call_id = uuid.uuid4().hex
        try:
            with self.db.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mcp_calls (
                        id, backend, server_name, tool_name, input_json, output_json,
                        is_error, error, started_at, duration_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        call_id,
                        "sandbox",
                        server_name,
                        tool_name,
                        _json_value(input_payload),
                        _json_value(output) if output is not None else None,
                        1 if is_error else 0,
                        error,
                        int(time.time()),
                        duration_ms,
                    ),
                )
        except Exception:
            logger.exception("mcp sandbox call insert failed")
        return call_id

    def list_calls(
        self,
        *,
        conversation_id: str | None = None,
        cli_session_id: str | None = None,
        server_name: str | None = None,
        tool_name: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("conversation_id", conversation_id),
            ("cli_session_id", cli_session_id),
            ("server_name", server_name),
            ("tool_name", tool_name),
        ):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        with self.db.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, conversation_id, segment_id, cli_session_id, backend,
                       server_name, tool_name, tool_use_id, input_json, output_json,
                       is_error, error, started_at, duration_ms
                FROM mcp_calls
                {where}
                ORDER BY started_at DESC
                LIMIT ?
                """,
                params,
            )
            rows = cur.fetchall()
        return [_row_to_dict(row) for row in rows]

    def get_call(self, call_id: str) -> dict[str, Any] | None:
        with self.db.cursor() as cur:
            cur.execute(
                """
                SELECT id, conversation_id, segment_id, cli_session_id, backend,
                       server_name, tool_name, tool_use_id, input_json, output_json,
                       is_error, error, started_at, duration_ms
                FROM mcp_calls WHERE id = ?
                """,
                (call_id,),
            )
            row = cur.fetchone()
        return _row_to_dict(row) if row else None


def _json_value(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps({"__unserializable__": str(value)})


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "segment_id": row["segment_id"],
        "cli_session_id": row["cli_session_id"],
        "backend": row["backend"],
        "server_name": row["server_name"],
        "tool_name": row["tool_name"],
        "tool_use_id": row["tool_use_id"],
        "input": _maybe_json(row["input_json"]),
        "output": _maybe_json(row["output_json"]),
        "is_error": bool(row["is_error"]),
        "error": row["error"],
        "started_at": row["started_at"],
        "duration_ms": row["duration_ms"],
    }


def _maybe_json(text: str | None) -> Any:
    if text is None:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


_LOGGER_INSTANCE: McpCallLogger | None = None


def get_call_logger() -> McpCallLogger:
    global _LOGGER_INSTANCE
    if _LOGGER_INSTANCE is None:
        _LOGGER_INSTANCE = McpCallLogger()
    return _LOGGER_INSTANCE


def set_call_logger_for_tests(logger_obj: McpCallLogger | None) -> None:
    global _LOGGER_INSTANCE
    _LOGGER_INSTANCE = logger_obj
