"""验证 MCP bridge server 的 stdio 帧格式——必须为 newline-delimited JSON。

覆盖 Task 11 AC 的隐含约束：Claude Code CLI（以及 ``mcp.server.stdio``）只
认 "一行一条 JSON、\\n 分隔" 的 stdio transport。若退回 LSP Content-Length
帧，消息会被静默吞掉且 AC4（浏览器 SSE tool_use 事件）永远不会触发。

这些断言与 ``_bootstrap`` 无关——纯 I/O 层验证，不需要网络或下游 MCP。
"""

from __future__ import annotations

import io
import json

from src.mcp_bridge.server import _read_message, _write_message


def test_read_message_parses_one_json_per_line() -> None:
    stream = io.BytesIO(
        b'{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
        b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n',
    )
    first = _read_message(stream)
    second = _read_message(stream)
    third = _read_message(stream)
    assert first == {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    assert second == {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    assert third is None  # EOF


def test_read_message_skips_blank_lines() -> None:
    stream = io.BytesIO(b"\n\r\n" + b'{"jsonrpc":"2.0","id":9,"method":"ping"}\n')
    assert _read_message(stream) == {"jsonrpc": "2.0", "id": 9, "method": "ping"}


def test_read_message_surfaces_parse_error() -> None:
    stream = io.BytesIO(b"not json at all\n")
    result = _read_message(stream)
    assert result is not None
    assert "__parse_error__" in result


def test_write_message_emits_newline_terminated_json() -> None:
    stream = io.BytesIO()
    _write_message(stream, {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
    payload = stream.getvalue()
    assert payload.endswith(b"\n")
    # 不允许 Content-Length 头——那是 LSP 帧，MCP CLI 不会解析
    assert not payload.startswith(b"Content-Length")
    # 去掉行尾换行后应为合法 JSON
    assert json.loads(payload.rstrip(b"\n").decode("utf-8")) == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"ok": True},
    }


def test_write_message_body_contains_no_embedded_newline() -> None:
    """MCP 规范：单条消息体内部不得有未转义换行——否则拆帧会把一条切成两条。"""
    stream = io.BytesIO()
    _write_message(
        stream,
        {"jsonrpc": "2.0", "id": 1, "result": {"text": "line1\nline2"}},
    )
    payload = stream.getvalue()
    # 精确 1 个 \n——在末尾；嵌入的换行必须被 JSON 编码为 \\n
    assert payload.count(b"\n") == 1
