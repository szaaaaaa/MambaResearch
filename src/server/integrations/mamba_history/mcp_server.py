"""mamba_history MCP server — cross-conversation reference (v3.3 multi-conversation).

启动方式::

    python -m src.server.integrations.mamba_history.mcp_server

设计动机
~~~~~~~~
v3.3 把"会话"还给 backend——每条 conversation 绑死一个 backend，永不切换。
但用户偶尔需要"把另一条对话里的脚本/结论引过来"，这种**稀疏跨对话引用**
不应该常态化预注入（v3.2 hybrid MT 那条路），而是 backend 主动 lazy pull。

本 MCP server 暴露两个工具，让 backend 自己判断"要不要查"：

- ``search_conversations(query, k)`` —— 模糊搜本 project 下的对话标题 + 消息
- ``get_conversation_messages(conversation_id, last_n)`` —— 取指定对话最近 N 条

二者都按需调，**不**预 push 任何上下文 = token 开销 O(实际查询)。

设计取舍
~~~~~~~~
* **standalone**：直接读 ``~/.mambaresearch/mamba.db`` + ``projects.json``——
  不依赖 web 进程；可被 Claude SDK / Codex CLI 任一长生命子进程托管
* **per-request 读 active project**：每次 ``tools/call`` 重新读
  ``MAMBA_ACTIVE_PROJECT_PATH``，让用户切 project 不需要重启 MCP server
* **NDJSON 协议**：与 ``workspace.mcp_server`` 一致；与 Claude SDK / Codex
  stdio MCP transport 一致
* **LIKE 搜索 v1**：用 SQLite ``LIKE`` 简单 substring 匹配，不上 FTS5——
  对话历史规模通常 < 几百条，全表扫足够；FTS5 加 schema 复杂度收益不大
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


ACTIVE_PROJECT_ENV_VAR = "MAMBA_ACTIVE_PROJECT_PATH"
SERVER_NAME = "mamba-history"
SERVER_VERSION = "1.0.0"

_REGISTRY_PATH = Path.home() / ".mambaresearch" / "projects.json"
_DB_PATH = Path.home() / ".mambaresearch" / "mamba.db"


# ---------------------------------------------------------------------------
# stdio NDJSON 帧（与 workspace.mcp_server 同形）
# ---------------------------------------------------------------------------


def _read_message(stream: Any) -> dict[str, Any] | None:
    while True:
        line = stream.readline()
        if not line:
            return None
        stripped = line.strip()
        if not stripped:
            continue
        try:
            return json.loads(stripped.decode("utf-8"))
        except json.JSONDecodeError as exc:
            return {
                "__parse_error__": str(exc),
                "__raw__": stripped[:200].decode("utf-8", errors="replace"),
            }


def _write_message(stream: Any, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    stream.write(body + b"\n")
    stream.flush()


def _result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _tool_text_result(structured: Any) -> dict[str, Any]:
    text = json.dumps(structured, ensure_ascii=False)
    return {
        "structuredContent": structured,
        "content": [{"type": "text", "text": text}],
        "isError": False,
    }


def _tool_error_result(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


# ---------------------------------------------------------------------------
# Active project ↔ project_id 解析
# ---------------------------------------------------------------------------


def _resolve_active_project_id() -> tuple[str | None, str | None]:
    """读 env + projects.json，返回 active project_id 或错误信息。

    Returns
    -------
    (project_id, error_message)
        project_id 为 None 时 error_message 给出原因。
    """
    raw = os.environ.get(ACTIVE_PROJECT_ENV_VAR, "").strip()
    if not raw:
        return None, (
            f"{ACTIVE_PROJECT_ENV_VAR} 未设置——无法定位 active project。"
            "请先在 MambaResearch 选/建一个 project。"
        )
    if not _REGISTRY_PATH.exists():
        return None, (
            f"projects.json 不存在：{_REGISTRY_PATH}。"
            "MambaResearch 后端可能从未启动过。"
        )
    try:
        registry = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"projects.json 读取失败：{exc}"
    projects = registry.get("projects") or []
    target = Path(raw).resolve()
    for proj in projects:
        if not isinstance(proj, dict):
            continue
        proj_path = proj.get("path")
        if isinstance(proj_path, str) and Path(proj_path).resolve() == target:
            proj_id = proj.get("id")
            if isinstance(proj_id, str) and proj_id:
                return proj_id, None
    return None, (
        f"projects.json 中找不到与 {ACTIVE_PROJECT_ENV_VAR}={raw} 匹配的项目。"
    )


# ---------------------------------------------------------------------------
# DB 访问（直读 mamba.db；与后端共享同一文件，WAL 并发安全）
# ---------------------------------------------------------------------------


def _open_db() -> sqlite3.Connection | None:
    if not _DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Tool descriptors
# ---------------------------------------------------------------------------


def _tool_descriptors() -> list[dict[str, Any]]:
    return [
        {
            "name": "search_conversations",
            "description": (
                "在 active project 范围内模糊搜对话——同时匹配标题与消息正文。"
                "返回最近活跃的前 k 条命中。常用场景：用户问『我之前在另一条对话"
                "讨论 X 的结论是什么』 → backend 调本工具找到 conv_id，"
                "再用 get_conversation_messages 取细节。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键字；空字符串返回最近活跃的 k 条。",
                    },
                    "k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 5,
                        "description": "返回条数上限（默认 5）。",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_conversation_messages",
            "description": (
                "取指定 conversation 的最近 N 条消息（按时间升序返回，方便阅读）。"
                "返回每条 ``{role, text, served_by, tool_use_summary, created_at}``。"
                "只读，不影响那条对话本身的状态。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "conversation_id": {
                        "type": "string",
                        "description": "通过 search_conversations 拿到的 conv_id。",
                    },
                    "last_n": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "default": 20,
                        "description": "取最近 N 条（默认 20）。",
                    },
                },
                "required": ["conversation_id"],
                "additionalProperties": False,
            },
        },
    ]


# ---------------------------------------------------------------------------
# Tool 调用分派
# ---------------------------------------------------------------------------


def _call_search_conversations(
    arguments: dict[str, Any], project_id: str
) -> dict[str, Any]:
    query_raw = arguments.get("query", "")
    if not isinstance(query_raw, str):
        return _tool_error_result("query 必须是字符串（空字符串表示返回最近活跃）")
    k_raw = arguments.get("k", 5)
    try:
        k = int(k_raw)
    except (TypeError, ValueError):
        return _tool_error_result("k 必须是整数")
    if k < 1 or k > 50:
        return _tool_error_result("k 须在 [1, 50]")

    conn = _open_db()
    if conn is None:
        return _tool_error_result(f"mamba.db 不存在：{_DB_PATH}")
    try:
        query = query_raw.strip()
        if not query:
            # 空 query → 直接返回该项目最近 k 条
            cur = conn.execute(
                "SELECT id, title, backend, created_at, last_active_at "
                "FROM conversations WHERE project_id = ? "
                "ORDER BY last_active_at DESC LIMIT ?",
                (project_id, k),
            )
            rows = cur.fetchall()
            results = [
                {
                    "conversation_id": r["id"],
                    "title": r["title"] or "",
                    "backend": r["backend"],
                    "last_active_at": r["last_active_at"],
                    "matched_in": "recent",
                    "snippet": "",
                }
                for r in rows
            ]
            return _tool_text_result({"conversations": results, "query": ""})

        like = f"%{query}%"
        # 同时匹配 title 与 message text（两个 UNION），按 last_active_at desc
        cur = conn.execute(
            """
            SELECT c.id AS conv_id,
                   c.title,
                   c.backend,
                   c.last_active_at,
                   'title' AS matched_in,
                   '' AS snippet
            FROM conversations c
            WHERE c.project_id = ? AND c.title LIKE ?
            UNION
            SELECT c.id,
                   c.title,
                   c.backend,
                   c.last_active_at,
                   'message' AS matched_in,
                   substr(m.text, 1, 200) AS snippet
            FROM conversations c
            JOIN messages m ON m.conversation_id = c.id
            WHERE c.project_id = ? AND m.text LIKE ?
            ORDER BY last_active_at DESC
            LIMIT ?
            """,
            (project_id, like, project_id, like, k),
        )
        rows = cur.fetchall()
        results = [
            {
                "conversation_id": r["conv_id"],
                "title": r["title"] or "",
                "backend": r["backend"],
                "last_active_at": r["last_active_at"],
                "matched_in": r["matched_in"],
                "snippet": r["snippet"] or "",
            }
            for r in rows
        ]
        return _tool_text_result({"conversations": results, "query": query})
    finally:
        conn.close()


def _call_get_conversation_messages(
    arguments: dict[str, Any], project_id: str
) -> dict[str, Any]:
    conv_id_raw = arguments.get("conversation_id")
    if not isinstance(conv_id_raw, str) or not conv_id_raw.strip():
        return _tool_error_result("conversation_id 必填")
    last_n_raw = arguments.get("last_n", 20)
    try:
        last_n = int(last_n_raw)
    except (TypeError, ValueError):
        return _tool_error_result("last_n 必须是整数")
    if last_n < 1 or last_n > 200:
        return _tool_error_result("last_n 须在 [1, 200]")

    conn = _open_db()
    if conn is None:
        return _tool_error_result(f"mamba.db 不存在：{_DB_PATH}")
    try:
        conv_id = conv_id_raw.strip()
        # 跨 project 安全护栏：只能查 active project 下的 conversation
        cur = conn.execute(
            "SELECT id, project_id, title, backend FROM conversations WHERE id = ?",
            (conv_id,),
        )
        conv_row = cur.fetchone()
        if conv_row is None:
            return _tool_error_result(f"conversation 不存在：{conv_id}")
        if conv_row["project_id"] != project_id:
            return _tool_error_result(
                f"conversation {conv_id} 属于其它 project，"
                "本工具只允许查 active project 内的对话。"
            )

        # 取最后 last_n 条；用子查询拿尾部，外层按 created_at 升序方便阅读
        cur = conn.execute(
            """
            SELECT role, text, served_by, tool_use_summary, created_at
            FROM (
              SELECT id, role, text, served_by, tool_use_summary, created_at
              FROM messages WHERE conversation_id = ?
              ORDER BY created_at DESC, id DESC
              LIMIT ?
            )
            ORDER BY created_at ASC, id ASC
            """,
            (conv_id, last_n),
        )
        rows = cur.fetchall()
        messages = [
            {
                "role": r["role"],
                "text": r["text"],
                "served_by": r["served_by"],
                "tool_use_summary": r["tool_use_summary"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
        return _tool_text_result(
            {
                "conversation_id": conv_id,
                "title": conv_row["title"] or "",
                "backend": conv_row["backend"],
                "messages": messages,
                "returned_count": len(messages),
            }
        )
    finally:
        conn.close()


_TOOL_DISPATCH = {
    "search_conversations": _call_search_conversations,
    "get_conversation_messages": _call_get_conversation_messages,
}


# ---------------------------------------------------------------------------
# Request handlers
# ---------------------------------------------------------------------------


def _handle_initialize(msg_id: Any) -> dict[str, Any]:
    return _result(
        msg_id,
        {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "capabilities": {"tools": {}},
        },
    )


def _handle_tools_list(msg_id: Any) -> dict[str, Any]:
    return _result(msg_id, {"tools": _tool_descriptors()})


def _handle_tools_call(msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    name = str(params.get("name") or "").strip()
    arguments = params.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}

    handler = _TOOL_DISPATCH.get(name)
    if handler is None:
        return _result(
            msg_id,
            _tool_error_result(
                f"未知工具：{name}（可用：{sorted(_TOOL_DISPATCH)}）"
            ),
        )

    project_id, err = _resolve_active_project_id()
    if project_id is None:
        return _result(msg_id, _tool_error_result(err or "active project 解析失败"))

    try:
        result = handler(arguments, project_id)
    except Exception as exc:  # noqa: BLE001
        return _result(msg_id, _tool_error_result(f"工具内部错误：{exc}"))
    return _result(msg_id, result)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def _main_loop() -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    while True:
        message = await asyncio.to_thread(_read_message, stdin)
        if message is None:
            return
        if "__parse_error__" in message:
            await asyncio.to_thread(
                _write_message,
                stdout,
                _error(None, -32700, f"parse error: {message['__parse_error__']}"),
            )
            continue

        msg_id = message.get("id")
        method = str(message.get("method") or "").strip()
        params = dict(message.get("params") or {})

        try:
            if method == "initialize":
                response = _handle_initialize(msg_id)
            elif method in {"initialized", "notifications/initialized"}:
                continue
            elif method == "tools/list":
                response = _handle_tools_list(msg_id)
            elif method == "tools/call":
                response = _handle_tools_call(msg_id, params)
            else:
                response = _error(msg_id, -32601, f"method not supported: {method}")
        except Exception as exc:  # noqa: BLE001
            response = _error(msg_id, -32000, f"internal error: {exc}")

        await asyncio.to_thread(_write_message, stdout, response)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MambaResearch mamba_history MCP server (stdio NDJSON JSON-RPC)",
    )
    parser.parse_args()
    asyncio.run(_main_loop())


# ---------------------------------------------------------------------------
# Server-local MCP 配置
# ---------------------------------------------------------------------------

DEFAULT_SERVER_KEY = "mamba_history"


def default_mcp_config(root: Path) -> dict[str, dict[str, Any]]:
    """返回 Mamba History Research plugin 使用的 stdio server 配置。"""
    resolved_root = str(root.resolve())
    return {
        DEFAULT_SERVER_KEY: {
            "type": "stdio",
            "command": sys.executable,
            "args": [
                "-m",
                "src.server.integrations.mamba_history.mcp_server",
            ],
            "env": {"PYTHONPATH": resolved_root},
        },
    }


if __name__ == "__main__":
    main()
