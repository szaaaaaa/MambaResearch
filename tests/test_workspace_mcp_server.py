"""Workspace MCP server 端到端测试。

不 spawn 实际子进程——直接调内部 ``_handle_*`` 函数；这样既快又能精确控制
``MAMBA_ACTIVE_PROJECT_PATH`` env、tmp_path 和 db cache 状态。

覆盖：
- tools/list 返回 5 个工具
- tools/call scan / classify_one / list / set_user_override / stats
- active project 缺失时 isError=true（非 JSON-RPC 错——业务级失败）
- classify_one 在文件未入库时拒绝
- 未知工具名 / unsupported method 各自走对应错误路径
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.server.projects.workspace import save_workspace, WorkspaceConfig
from src.server.workspace import mcp_server
from src.server.workspace.classification import (
    PRIMARY_BUCKETS,
    reset_db_cache,
)


@pytest.fixture(autouse=True)
def _reset_db_cache():
    yield
    reset_db_cache()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """临时 project + 注入 MAMBA_ACTIVE_PROJECT_PATH env。"""
    proj = tmp_path / "proj"
    proj.mkdir()
    src = proj / "src"
    src.mkdir()
    (src / "a.py").write_bytes(b"print(1)")
    (src / "b.txt").write_bytes(b"hello")
    save_workspace(str(proj), WorkspaceConfig(source_dirs=[str(src.resolve())]))
    monkeypatch.setenv(mcp_server.ACTIVE_PROJECT_ENV_VAR, str(proj))
    return proj


def _call(method: str, params: dict | None = None, msg_id: int = 1) -> dict:
    """直接走 handler——测试更快、更精确。"""
    if method == "initialize":
        return mcp_server._handle_initialize(msg_id)
    if method == "tools/list":
        return mcp_server._handle_tools_list(msg_id)
    if method == "tools/call":
        return mcp_server._handle_tools_call(msg_id, params or {})
    raise AssertionError(f"unknown method in test helper: {method}")


def _structured(response: dict) -> dict:
    """从 tools/call 响应里抠 structuredContent。"""
    return response["result"]["structuredContent"]


def _is_error(response: dict) -> bool:
    return bool(response["result"].get("isError"))


def _error_text(response: dict) -> str:
    return response["result"]["content"][0]["text"]


# ---------------------------------------------------------------------------
# initialize / tools/list
# ---------------------------------------------------------------------------


def test_initialize_returns_protocol_info():
    resp = _call("initialize")
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert resp["result"]["serverInfo"]["name"] == mcp_server.SERVER_NAME


def test_tools_list_exposes_five_tools(project: Path):
    resp = _call("tools/list")
    names = sorted(t["name"] for t in resp["result"]["tools"])
    assert names == ["classify_one", "list", "scan", "set_user_override", "stats"]
    # 每个工具都有 inputSchema
    for tool in resp["result"]["tools"]:
        assert tool["inputSchema"]["type"] == "object"


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


def test_scan_picks_up_files(project: Path):
    resp = _call("tools/call", {"name": "scan", "arguments": {}})
    payload = _structured(resp)
    assert payload["scanned"] == 2
    assert payload["new"] == 2
    assert len(payload["per_source"]) == 1


def test_scan_with_explicit_source_dir(project: Path, tmp_path: Path):
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "x.md").write_bytes(b"# title")
    resp = _call(
        "tools/call",
        {"name": "scan", "arguments": {"source_dir": str(extra)}},
    )
    payload = _structured(resp)
    assert payload["scanned"] == 1
    assert payload["new"] == 1


def test_scan_without_source_dirs_returns_error(tmp_path: Path, monkeypatch):
    """workspace.json 没 source_dirs 且未传参 → isError=true 提示用户配置。"""
    proj = tmp_path / "empty_proj"
    proj.mkdir()
    monkeypatch.setenv(mcp_server.ACTIVE_PROJECT_ENV_VAR, str(proj))
    resp = _call("tools/call", {"name": "scan", "arguments": {}})
    assert _is_error(resp)
    assert "source_dirs" in _error_text(resp)


# ---------------------------------------------------------------------------
# classify_one
# ---------------------------------------------------------------------------


def test_classify_one_after_scan(project: Path):
    _call("tools/call", {"name": "scan", "arguments": {}})
    target = str((project / "src" / "a.py").resolve())
    resp = _call(
        "tools/call",
        {
            "name": "classify_one",
            "arguments": {
                "path": target,
                "primary_bucket": "experiment",
                "subtype": "train_script",
                "summary": "训练入口脚本",
                "tags": ["python", "entry"],
                "confidence": 0.85,
                "classifier_model": "claude-opus-4-7",
            },
        },
    )
    payload = _structured(resp)
    assert payload["wrote"] is True
    assert payload["primary_bucket"] == "experiment"


def test_classify_one_rejects_unknown_path(project: Path):
    resp = _call(
        "tools/call",
        {
            "name": "classify_one",
            "arguments": {
                "path": str(project / "nope.py"),
                "primary_bucket": "experiment",
            },
        },
    )
    assert _is_error(resp)
    assert "未入索引" in _error_text(resp)


def test_classify_one_rejects_invalid_bucket(project: Path):
    _call("tools/call", {"name": "scan", "arguments": {}})
    target = str((project / "src" / "a.py").resolve())
    resp = _call(
        "tools/call",
        {
            "name": "classify_one",
            "arguments": {"path": target, "primary_bucket": "bogus"},
        },
    )
    assert _is_error(resp)


def test_classify_one_respects_user_override(project: Path):
    _call("tools/call", {"name": "scan", "arguments": {}})
    target = str((project / "src" / "a.py").resolve())
    # 先标 user_override
    _call(
        "tools/call",
        {
            "name": "set_user_override",
            "arguments": {
                "path": target,
                "primary_bucket": "literature",
                "subtype": "paper_pdf",
            },
        },
    )
    # LLM 再尝试改类——respect_override=True 应只刷指纹不动分类
    resp = _call(
        "tools/call",
        {
            "name": "classify_one",
            "arguments": {
                "path": target,
                "primary_bucket": "experiment",
                "confidence": 0.9,
            },
        },
    )
    payload = _structured(resp)
    assert payload["wrote"] is False
    assert payload["respected_override"] is True


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_filters_by_bucket(project: Path):
    _call("tools/call", {"name": "scan", "arguments": {}})
    target = str((project / "src" / "a.py").resolve())
    _call(
        "tools/call",
        {
            "name": "classify_one",
            "arguments": {
                "path": target,
                "primary_bucket": "experiment",
                "confidence": 0.9,
            },
        },
    )
    resp = _call(
        "tools/call",
        {"name": "list", "arguments": {"bucket": "experiment", "limit": 100}},
    )
    payload = _structured(resp)
    paths = [f["path"] for f in payload["files"]]
    assert target in paths


def test_list_rejects_invalid_bucket(project: Path):
    resp = _call(
        "tools/call",
        {"name": "list", "arguments": {"bucket": "made_up"}},
    )
    assert _is_error(resp)


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


def test_stats_returns_all_buckets(project: Path):
    _call("tools/call", {"name": "scan", "arguments": {}})
    resp = _call("tools/call", {"name": "stats", "arguments": {}})
    payload = _structured(resp)
    assert payload["total"] == 2
    # 所有 bucket 都应在响应里（含 0 计数）
    for bucket in PRIMARY_BUCKETS:
        assert bucket in payload["by_bucket"]
    assert payload["by_bucket"]["unknown"] == 2


# ---------------------------------------------------------------------------
# Active project 缺失 / 错路径
# ---------------------------------------------------------------------------


def test_missing_active_project_returns_error(monkeypatch):
    monkeypatch.delenv(mcp_server.ACTIVE_PROJECT_ENV_VAR, raising=False)
    resp = _call("tools/call", {"name": "stats", "arguments": {}})
    assert _is_error(resp)
    assert "MAMBA_ACTIVE_PROJECT_PATH" in _error_text(resp)


def test_active_project_path_not_a_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv(mcp_server.ACTIVE_PROJECT_ENV_VAR, str(tmp_path / "ghost"))
    resp = _call("tools/call", {"name": "stats", "arguments": {}})
    assert _is_error(resp)
    assert "不存在" in _error_text(resp) or "目录" in _error_text(resp)


# ---------------------------------------------------------------------------
# 未知工具 / unsupported method
# ---------------------------------------------------------------------------


def test_unknown_tool_returns_error(project: Path):
    resp = _call("tools/call", {"name": "nope", "arguments": {}})
    assert _is_error(resp)
    assert "未知工具" in _error_text(resp)


# ---------------------------------------------------------------------------
# NDJSON 帧 helpers
# ---------------------------------------------------------------------------


def test_ndjson_read_write_roundtrip(tmp_path: Path):
    """直接验帧编解码，确保协议形状不会因重构悄悄漂移。"""
    import io

    out = io.BytesIO()
    mcp_server._write_message(out, {"jsonrpc": "2.0", "id": 1, "result": {"x": 2}})
    raw = out.getvalue()
    assert raw.endswith(b"\n")
    line = raw.strip()
    assert json.loads(line) == {"jsonrpc": "2.0", "id": 1, "result": {"x": 2}}

    inp = io.BytesIO(raw)
    msg = mcp_server._read_message(inp)
    assert msg["result"]["x"] == 2


def test_ndjson_parse_error_returns_marker(tmp_path: Path):
    import io

    inp = io.BytesIO(b"not json\n")
    msg = mcp_server._read_message(inp)
    assert msg is not None
    assert "__parse_error__" in msg
