"""MCP tool 调用历史 logger（Stage 3 Task 2）。

设计要点
~~~~~~~~
- 单进程级单例 ``McpCallLogger``——session_manager 在 SSE 事件分发处接它，
  无 backend 时直接写 ``backend='sandbox'``（Stage 3 Task 3 sandbox 路径用）
- 不在事件流上做拦截/转换——只观测、写库、返回；任何异常吞掉记 log（不能让
  logger 崩溃影响主对话）
- ``observe_claude_event`` / ``observe_codex_event`` 各自处理对应 SSE 事件
  payload；按 backend 拆开是因为两边事件 schema 不同（claude_code SDK 是
  Anthropic Message 格式；codex 是 JSON-RPC notification 形式）
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from src.server.projects.db import MambaDb, get_db


logger = logging.getLogger(__name__)


# Claude SDK 把 MCP tool 的命名规范统一为 ``mcp__<server>__<tool>``。
# 解析时既能匹配双下划线版（SDK 标准），也宽容地接受单下划线 ``mcp_``
# 前缀（一些第三方 wrapper 用）。
_MCP_NAME_RE = re.compile(r"^mcp(?:__|_)([^_]+)__(.+)$")
_MCP_NAME_RE_LOOSE = re.compile(r"^mcp__([^_]+(?:_[^_]+)*?)__(.+)$")


def _parse_mcp_tool_name(name: str) -> tuple[str, str] | None:
    """``mcp__<server>__<tool>`` → ``(server, tool)``；非 MCP tool 返 None。

    Server 名可能含下划线（``mamba_workspace``），所以严格按 ``__`` 分割：
    ``mcp__mamba_workspace__scan`` → server=``mamba_workspace``, tool=``scan``。
    """
    if not name.startswith("mcp__"):
        return None
    rest = name[len("mcp__"):]
    if "__" not in rest:
        return None
    server, _, tool = rest.partition("__")
    if not server or not tool:
        return None
    return server, tool


@dataclass
class McpCallContext:
    """observe_* 调用方传给 logger 的会话上下文。

    全部 None 也是合法（sandbox 直调 / 未绑会话时）。
    """

    conversation_id: str | None = None
    segment_id: str | None = None
    cli_session_id: str | None = None


class McpCallLogger:
    """``mcp_calls`` 表的写入封装。

    ``observe_*`` 系列方法按 backend 接收原生事件 payload，识别其中的
    ``tool_use`` / ``tool_result`` 块并落库——pending tool_use 暂存
    在内存里，匹配到 tool_result 后回填 output/duration。进程重启时
    pending 表丢失：那种情况下对话本身已断，没意义保留。
    """

    def __init__(self, db: MambaDb | None = None) -> None:
        self._db = db
        # tool_use_id → 已写入的 mcp_calls.id；tool_result 到来时按此回填
        self._pending: dict[str, tuple[str, float]] = {}

    @property
    def db(self) -> MambaDb:
        return self._db or get_db()

    # -----------------------------------------------------------------
    # 内部 IO
    # -----------------------------------------------------------------

    def _insert_call(
        self,
        *,
        backend: str,
        server_name: str,
        tool_name: str,
        tool_use_id: str | None,
        input_payload: Any,
        ctx: McpCallContext,
    ) -> str:
        call_id = uuid.uuid4().hex
        try:
            input_json = json.dumps(input_payload, ensure_ascii=False)
        except (TypeError, ValueError):
            input_json = json.dumps({"__unserializable__": str(input_payload)})
        try:
            with self.db.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mcp_calls (
                        id, conversation_id, segment_id, cli_session_id,
                        backend, server_name, tool_name, tool_use_id,
                        input_json, started_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        call_id,
                        ctx.conversation_id,
                        ctx.segment_id,
                        ctx.cli_session_id,
                        backend,
                        server_name,
                        tool_name,
                        tool_use_id,
                        input_json,
                        int(time.time()),
                    ),
                )
        except Exception:  # noqa: BLE001
            logger.exception("mcp_calls insert failed")
            return call_id
        return call_id

    def _finalize_call(
        self,
        *,
        call_id: str,
        started_at: float,
        output: Any,
        is_error: bool,
        error: str | None,
    ) -> None:
        duration_ms = int((time.time() - started_at) * 1000)
        try:
            output_json: str | None
            if output is None:
                output_json = None
            else:
                try:
                    output_json = json.dumps(output, ensure_ascii=False)
                except (TypeError, ValueError):
                    output_json = json.dumps({"__unserializable__": str(output)})
            with self.db.cursor() as cur:
                cur.execute(
                    """
                    UPDATE mcp_calls
                    SET output_json = ?, is_error = ?, error = ?, duration_ms = ?
                    WHERE id = ?
                    """,
                    (
                        output_json,
                        1 if is_error else 0,
                        error,
                        duration_ms,
                        call_id,
                    ),
                )
        except Exception:  # noqa: BLE001
            logger.exception("mcp_calls finalize failed")

    # -----------------------------------------------------------------
    # 公开 observe API（Claude）
    # -----------------------------------------------------------------

    def observe_claude_event(self, payload: Any, ctx: McpCallContext) -> None:
        """处理 Claude SDK 一帧 SSE 事件。

        关注两种 block：
        - ``tool_use``     —— 含 ``id`` / ``name`` / ``input``，开始一次调用
        - ``tool_result``  —— 含 ``tool_use_id`` / ``content`` / ``is_error``
                               回填上一条
        """
        if not isinstance(payload, dict):
            return
        msg_type = payload.get("type")
        if msg_type not in ("assistant", "user"):
            return
        content = payload.get("content")
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "tool_use":
                self._on_tool_use(block, ctx, backend="claude")
            elif block_type == "tool_result":
                self._on_tool_result(block)

    def _on_tool_use(
        self, block: dict[str, Any], ctx: McpCallContext, *, backend: str
    ) -> None:
        name = str(block.get("name") or "")
        parsed = _parse_mcp_tool_name(name)
        if parsed is None:
            return
        server_name, tool_name = parsed
        tool_use_id = block.get("id")
        input_payload = block.get("input")
        call_id = self._insert_call(
            backend=backend,
            server_name=server_name,
            tool_name=tool_name,
            tool_use_id=str(tool_use_id) if tool_use_id else None,
            input_payload=input_payload,
            ctx=ctx,
        )
        if tool_use_id:
            self._pending[str(tool_use_id)] = (call_id, time.time())

    def _on_tool_result(self, block: dict[str, Any]) -> None:
        tool_use_id = block.get("tool_use_id")
        if not tool_use_id:
            return
        match = self._pending.pop(str(tool_use_id), None)
        if match is None:
            return
        call_id, started_at = match
        is_error = bool(block.get("is_error"))
        content = block.get("content")
        error_text = None
        if is_error:
            try:
                error_text = json.dumps(content, ensure_ascii=False)[:500]
            except (TypeError, ValueError):
                error_text = str(content)[:500]
        self._finalize_call(
            call_id=call_id,
            started_at=started_at,
            output=None if is_error else content,
            is_error=is_error,
            error=error_text,
        )

    # -----------------------------------------------------------------
    # 公开 observe API（Codex）
    # -----------------------------------------------------------------

    def observe_codex_event(self, payload: Any, ctx: McpCallContext) -> None:
        """处理 Codex SSE 一帧 ``codex_message`` payload。

        Codex 把 MCP tool 调用通过 JSON-RPC notification 的形式发回，常见 method：
        - ``item/agent_message`` 含 tool_use / tool_result block（与 Claude 同形）
        - ``item/tool_use`` / ``item/tool_result``（上层封装）

        Codex schema 在 5b 阶段尚未完全稳定，本方法采取宽容策略：扫整帧 dict
        递归找含 ``mcp__`` 前缀 ``name`` 字段的对象，按 tool_use 处理。这避免
        与 Codex 内部演进强耦合；一旦 schema 稳定可以收紧。
        """
        if not isinstance(payload, dict):
            return
        for block in _walk_dicts(payload):
            block_type = block.get("type")
            if block_type == "tool_use":
                self._on_tool_use(block, ctx, backend="codex")
            elif block_type == "tool_result":
                self._on_tool_result(block)

    # -----------------------------------------------------------------
    # Sandbox（Stage 3 Task 3 用）
    # -----------------------------------------------------------------

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
        """sandbox 直调走完整路径：起一行 + 立即 finalize。"""
        call_id = self._insert_call(
            backend="sandbox",
            server_name=server_name,
            tool_name=tool_name,
            tool_use_id=None,
            input_payload=input_payload,
            ctx=McpCallContext(),
        )
        # 不走 _finalize_call 的"算 duration"逻辑——sandbox 调用直接传 duration_ms
        try:
            output_json: str | None
            if output is None:
                output_json = None
            else:
                try:
                    output_json = json.dumps(output, ensure_ascii=False)
                except (TypeError, ValueError):
                    output_json = json.dumps({"__unserializable__": str(output)})
            with self.db.cursor() as cur:
                cur.execute(
                    """
                    UPDATE mcp_calls
                    SET output_json = ?, is_error = ?, error = ?, duration_ms = ?
                    WHERE id = ?
                    """,
                    (output_json, 1 if is_error else 0, error, duration_ms, call_id),
                )
        except Exception:  # noqa: BLE001
            logger.exception("sandbox finalize failed")
        return call_id

    # -----------------------------------------------------------------
    # 查询接口（routes 用）
    # -----------------------------------------------------------------

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
        if conversation_id:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)
        if cli_session_id:
            clauses.append("cli_session_id = ?")
            params.append(cli_session_id)
        if server_name:
            clauses.append("server_name = ?")
            params.append(server_name)
        if tool_name:
            clauses.append("tool_name = ?")
            params.append(tool_name)
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


def _walk_dicts(obj: Any):
    """深度遍历对象产出所有 dict——Codex 帧结构松散需要这样找 tool_use 块。"""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_dicts(v)


# ---------------------------------------------------------------------------
# 进程级单例
# ---------------------------------------------------------------------------

_LOGGER_INSTANCE: McpCallLogger | None = None


def get_call_logger() -> McpCallLogger:
    global _LOGGER_INSTANCE
    if _LOGGER_INSTANCE is None:
        _LOGGER_INSTANCE = McpCallLogger()
    return _LOGGER_INSTANCE


def set_call_logger_for_tests(logger_obj: McpCallLogger | None) -> None:
    global _LOGGER_INSTANCE
    _LOGGER_INSTANCE = logger_obj
