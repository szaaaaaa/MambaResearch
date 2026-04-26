"""MCP call logger 测试（Stage 3 Task 2）。

覆盖：
- 工具名解析：``mcp__server__tool`` 模式 / 含下划线的 server 名
- observe_claude_event 识别 tool_use → 入库 ``input_json``
- 后续 tool_result 按 ``tool_use_id`` 回填 ``output_json`` / ``duration_ms``
- ``is_error`` tool_result 入库 ``error`` 字段而非 output
- 非 MCP tool（普通 Read / Bash 等）静默跳过
- observe_codex_event 宽容扫整帧找 tool_use
- record_sandbox_call 直接写完整记录
- list_calls / get_call 形状
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.server.mcp.call_logger import (
    McpCallContext,
    McpCallLogger,
    _parse_mcp_tool_name,
)
from src.server.projects.db import MambaDb, set_db_for_tests


@pytest.fixture
def db(tmp_path: Path) -> MambaDb:
    instance = MambaDb(db_path=tmp_path / "mamba.db")
    instance.connect()
    set_db_for_tests(instance)
    yield instance
    set_db_for_tests(None)


@pytest.fixture
def logger(db: MambaDb) -> McpCallLogger:
    return McpCallLogger(db=db)


# ---------------------------------------------------------------------------
# 工具名解析
# ---------------------------------------------------------------------------


def test_parse_mcp_tool_name_simple():
    assert _parse_mcp_tool_name("mcp__research_agent__plan") == ("research_agent", "plan")


def test_parse_mcp_tool_name_underscore_in_server():
    assert _parse_mcp_tool_name("mcp__mamba_workspace__classify_one") == (
        "mamba_workspace",
        "classify_one",
    )


def test_parse_mcp_tool_name_rejects_non_mcp():
    assert _parse_mcp_tool_name("Read") is None
    assert _parse_mcp_tool_name("Bash") is None
    assert _parse_mcp_tool_name("mcp__only_one_part") is None


# ---------------------------------------------------------------------------
# Claude 事件观测
# ---------------------------------------------------------------------------


def test_observe_assistant_tool_use_inserts_call(logger: McpCallLogger):
    payload = {
        "type": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "tool_abc",
                "name": "mcp__mamba_workspace__scan",
                "input": {"source_dir": "/foo"},
            }
        ],
    }
    logger.observe_claude_event(payload, McpCallContext(cli_session_id="sess1"))
    calls = logger.list_calls()
    assert len(calls) == 1
    c = calls[0]
    assert c["server_name"] == "mamba_workspace"
    assert c["tool_name"] == "scan"
    assert c["tool_use_id"] == "tool_abc"
    assert c["backend"] == "claude"
    assert c["cli_session_id"] == "sess1"
    assert c["input"] == {"source_dir": "/foo"}
    # 还没 finalize
    assert c["output"] is None
    assert c["duration_ms"] is None


def test_observe_tool_result_finalizes_pending_call(logger: McpCallLogger):
    use = {
        "type": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "tool_abc",
                "name": "mcp__mamba_workspace__scan",
                "input": {},
            }
        ],
    }
    logger.observe_claude_event(use, McpCallContext(cli_session_id="sess1"))
    # 模拟点 wall-clock 流逝
    time.sleep(0.01)
    result = {
        "type": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "tool_abc",
                "content": [{"type": "text", "text": "{\"scanned\": 5}"}],
                "is_error": False,
            }
        ],
    }
    logger.observe_claude_event(result, McpCallContext(cli_session_id="sess1"))
    calls = logger.list_calls()
    assert len(calls) == 1
    c = calls[0]
    assert c["output"] is not None
    assert c["is_error"] is False
    assert c["duration_ms"] is not None
    assert c["duration_ms"] >= 0


def test_observe_tool_result_with_error(logger: McpCallLogger):
    use = {
        "type": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "tool_x",
                "name": "mcp__mamba_workspace__classify_one",
                "input": {"path": "/bogus"},
            }
        ],
    }
    logger.observe_claude_event(use, McpCallContext())
    err = {
        "type": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "tool_x",
                "content": "未入索引：/bogus",
                "is_error": True,
            }
        ],
    }
    logger.observe_claude_event(err, McpCallContext())
    c = logger.list_calls()[0]
    assert c["is_error"] is True
    assert c["error"] is not None
    assert c["output"] is None


def test_non_mcp_tool_use_is_ignored(logger: McpCallLogger):
    payload = {
        "type": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "tool_y",
                "name": "Read",
                "input": {"file_path": "/x"},
            }
        ],
    }
    logger.observe_claude_event(payload, McpCallContext())
    assert logger.list_calls() == []


def test_non_assistant_payload_is_ignored(logger: McpCallLogger):
    logger.observe_claude_event({"type": "system", "subtype": "init"}, McpCallContext())
    logger.observe_claude_event("not even a dict", McpCallContext())
    logger.observe_claude_event(None, McpCallContext())
    assert logger.list_calls() == []


# ---------------------------------------------------------------------------
# Codex 事件观测
# ---------------------------------------------------------------------------


def test_observe_codex_event_walks_nested_dicts(logger: McpCallLogger):
    """Codex JSON-RPC notification 嵌套结构——logger 应该深度遍历找到 tool_use。"""
    payload = {
        "method": "item/agent_message",
        "params": {
            "msg": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "codex_tool_1",
                        "name": "mcp__mamba_workspace__list",
                        "input": {"bucket": "experiment"},
                    }
                ]
            }
        },
    }
    logger.observe_codex_event(payload, McpCallContext(cli_session_id="codex_sess"))
    c = logger.list_calls()[0]
    assert c["server_name"] == "mamba_workspace"
    assert c["tool_name"] == "list"
    assert c["backend"] == "codex"


# ---------------------------------------------------------------------------
# Sandbox 直调
# ---------------------------------------------------------------------------


def test_record_sandbox_call_writes_complete_row(logger: McpCallLogger):
    call_id = logger.record_sandbox_call(
        server_name="mamba_workspace",
        tool_name="stats",
        input_payload={},
        output={"total": 0},
        is_error=False,
        error=None,
        duration_ms=42,
    )
    c = logger.get_call(call_id)
    assert c is not None
    assert c["backend"] == "sandbox"
    assert c["duration_ms"] == 42
    assert c["output"] == {"total": 0}


# ---------------------------------------------------------------------------
# 查询过滤
# ---------------------------------------------------------------------------


def test_list_calls_filters(logger: McpCallLogger):
    for tool in ("scan", "list", "stats"):
        logger.observe_claude_event(
            {
                "type": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"id_{tool}",
                        "name": f"mcp__mamba_workspace__{tool}",
                        "input": {},
                    }
                ],
            },
            McpCallContext(cli_session_id="s_filter"),
        )
    only_scan = logger.list_calls(tool_name="scan")
    assert len(only_scan) == 1
    assert only_scan[0]["tool_name"] == "scan"
    by_session = logger.list_calls(cli_session_id="s_filter")
    assert len(by_session) == 3
