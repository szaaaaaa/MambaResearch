"""Zotero MCP server 端到端测试。

不 spawn 子进程——直接调内部 ``_handle_*``。
mock 走两层：
1. ``_client_factory``：替换为返回 fake client 的 lambda
2. ``load_zotero_credentials``：缺凭据测试通过 monkeypatch env 触发真实路径
"""
from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.server.integrations.zotero import mcp_server
from src.server.integrations.zotero.credentials import ZoteroCredentials


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def with_creds(monkeypatch: pytest.MonkeyPatch, fake_client: MagicMock) -> MagicMock:
    """注入合法凭据 env + 替换 client 工厂为 fake client 工厂。"""
    monkeypatch.setenv("ZOTERO_USER_ID", "12345")
    monkeypatch.setenv("ZOTERO_API_KEY", "test-key")
    monkeypatch.setattr(
        mcp_server, "_client_factory", lambda credentials=None: fake_client
    )
    return fake_client


@pytest.fixture
def no_creds(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("ZOTERO_USER_ID", raising=False)
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    # 确保 credentials.py 不会读到仓库根 .env
    monkeypatch.setattr(
        "src.server.integrations.zotero.credentials.ENV_PATH",
        tmp_path / "absent.env",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _call(method: str, params: dict | None = None, msg_id: int = 1) -> dict:
    if method == "initialize":
        return mcp_server._handle_initialize(msg_id)
    if method == "tools/list":
        return mcp_server._handle_tools_list(msg_id)
    if method == "tools/call":
        return mcp_server._handle_tools_call(msg_id, params or {})
    raise AssertionError(f"unknown method: {method}")


def _structured(resp: dict) -> Any:
    return resp["result"]["structuredContent"]


def _is_error(resp: dict) -> bool:
    return bool(resp["result"].get("isError"))


def _error_text(resp: dict) -> str:
    return resp["result"]["content"][0]["text"]


# ---------------------------------------------------------------------------
# initialize / tools/list
# ---------------------------------------------------------------------------


def test_initialize_returns_protocol_info():
    resp = _call("initialize")
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert resp["result"]["serverInfo"]["name"] == mcp_server.SERVER_NAME


def test_tools_list_lists_6_tools():
    resp = _call("tools/list")
    names = sorted(t["name"] for t in resp["result"]["tools"])
    assert names == [
        "add_tag",
        "download_pdf",
        "get_item",
        "list_collections",
        "search",
        "upload_pdf",
    ]


def test_tools_list_search_schema_required_query():
    resp = _call("tools/list")
    tools = {t["name"]: t for t in resp["result"]["tools"]}
    assert tools["search"]["inputSchema"]["required"] == ["query"]
    assert tools["upload_pdf"]["inputSchema"]["required"] == ["local_path"]
    assert tools["download_pdf"]["inputSchema"]["required"] == ["item_key", "dest_dir"]


# ---------------------------------------------------------------------------
# Credential gating —— 缺 ZOTERO_* env → isError + guidance
# ---------------------------------------------------------------------------


def test_tools_call_returns_isError_when_credentials_missing(no_creds):
    resp = _call("tools/call", {"name": "search", "arguments": {"query": "mamba"}})
    assert _is_error(resp)
    msg = _error_text(resp)
    assert "ZOTERO_USER_ID" in msg
    assert "ZOTERO_API_KEY" in msg
    assert "MambaResearch" in msg or "zotero.org" in msg


def test_credential_gating_applies_to_every_tool(no_creds):
    for tool in (
        "search",
        "list_collections",
        "get_item",
        "add_tag",
        "upload_pdf",
        "download_pdf",
    ):
        args = {
            "search": {"query": "x"},
            "list_collections": {},
            "get_item": {"item_key": "K"},
            "add_tag": {"item_key": "K", "tags": ["t"]},
            "upload_pdf": {"local_path": "/tmp/x.pdf"},
            "download_pdf": {"item_key": "K", "dest_dir": "/tmp/x"},
        }[tool]
        resp = _call("tools/call", {"name": tool, "arguments": args})
        assert _is_error(resp), f"{tool}: should be isError when creds missing"


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def test_search_passes_query_and_returns_items(with_creds: MagicMock):
    with_creds.search.return_value = [{"key": "I1", "title": "Mamba"}]
    resp = _call("tools/call", {"name": "search", "arguments": {"query": "mamba", "limit": 5}})
    assert not _is_error(resp)
    assert _structured(resp) == {"query": "mamba", "items": [{"key": "I1", "title": "Mamba"}]}
    with_creds.search.assert_called_once_with("mamba", limit=5)


def test_search_default_limit_20(with_creds: MagicMock):
    with_creds.search.return_value = []
    _call("tools/call", {"name": "search", "arguments": {"query": "x"}})
    with_creds.search.assert_called_once_with("x", limit=20)


def test_search_rejects_empty_query(with_creds):
    resp = _call("tools/call", {"name": "search", "arguments": {"query": "  "}})
    assert _is_error(resp)
    assert "query 必填" in _error_text(resp)


def test_search_rejects_out_of_range_limit(with_creds):
    resp = _call("tools/call", {"name": "search", "arguments": {"query": "x", "limit": 999}})
    assert _is_error(resp)
    assert "limit" in _error_text(resp)


def test_search_wraps_client_exception(with_creds: MagicMock):
    with_creds.search.side_effect = RuntimeError("network down")
    resp = _call("tools/call", {"name": "search", "arguments": {"query": "x"}})
    assert _is_error(resp)
    assert "network down" in _error_text(resp)


# ---------------------------------------------------------------------------
# list_collections
# ---------------------------------------------------------------------------


def test_list_collections_returns_items(with_creds: MagicMock):
    with_creds.list_collections.return_value = [{"key": "C1", "name": "Inbox"}]
    resp = _call("tools/call", {"name": "list_collections", "arguments": {}})
    assert _structured(resp) == {"collections": [{"key": "C1", "name": "Inbox"}]}


# ---------------------------------------------------------------------------
# get_item
# ---------------------------------------------------------------------------


def test_get_item_passes_key(with_creds: MagicMock):
    with_creds.get_item.return_value = {"title": "T"}
    resp = _call("tools/call", {"name": "get_item", "arguments": {"item_key": "ABC"}})
    assert _structured(resp) == {"item_key": "ABC", "data": {"title": "T"}}
    with_creds.get_item.assert_called_once_with("ABC")


def test_get_item_rejects_missing_key(with_creds):
    resp = _call("tools/call", {"name": "get_item", "arguments": {}})
    assert _is_error(resp)
    assert "item_key" in _error_text(resp)


# ---------------------------------------------------------------------------
# add_tag
# ---------------------------------------------------------------------------


def test_add_tag_happy_path(with_creds: MagicMock):
    with_creds.add_tag.return_value = {"ok": True, "tags": ["a", "b"]}
    resp = _call(
        "tools/call",
        {"name": "add_tag", "arguments": {"item_key": "K1", "tags": ["a", "b"]}},
    )
    assert not _is_error(resp)
    assert _structured(resp) == {"item_key": "K1", "tags": ["a", "b"]}


def test_add_tag_rejects_empty_tags(with_creds):
    resp = _call(
        "tools/call",
        {"name": "add_tag", "arguments": {"item_key": "K1", "tags": []}},
    )
    assert _is_error(resp)
    assert "至少含一个" in _error_text(resp)


def test_add_tag_rejects_non_string_tags(with_creds):
    resp = _call(
        "tools/call",
        {"name": "add_tag", "arguments": {"item_key": "K1", "tags": [123]}},
    )
    assert _is_error(resp)


def test_add_tag_propagates_client_failure(with_creds: MagicMock):
    with_creds.add_tag.return_value = {"ok": False, "error": "412 conflict"}
    resp = _call(
        "tools/call",
        {"name": "add_tag", "arguments": {"item_key": "K1", "tags": ["x"]}},
    )
    assert _is_error(resp)
    assert "412 conflict" in _error_text(resp)


# ---------------------------------------------------------------------------
# upload_pdf
# ---------------------------------------------------------------------------


def test_upload_pdf_passes_arguments(with_creds: MagicMock):
    with_creds.upload_pdf.return_value = {"ok": True, "item_key": "U1", "title": "T"}
    resp = _call(
        "tools/call",
        {
            "name": "upload_pdf",
            "arguments": {
                "local_path": "/tmp/p.pdf",
                "collection": "C1",
                "tags": ["mamba", "ssm"],
                "title": "T",
                "authors": ["A", "B"],
            },
        },
    )
    assert not _is_error(resp)
    assert _structured(resp)["item_key"] == "U1"
    with_creds.upload_pdf.assert_called_once_with(
        local_path="/tmp/p.pdf",
        collection="C1",
        tags=["mamba", "ssm"],
        title="T",
        authors=["A", "B"],
    )


def test_upload_pdf_rejects_missing_path(with_creds):
    resp = _call("tools/call", {"name": "upload_pdf", "arguments": {}})
    assert _is_error(resp)
    assert "local_path" in _error_text(resp)


def test_upload_pdf_propagates_client_failure(with_creds: MagicMock):
    with_creds.upload_pdf.return_value = {"ok": False, "error": "file not found: /x"}
    resp = _call(
        "tools/call",
        {"name": "upload_pdf", "arguments": {"local_path": "/x"}},
    )
    assert _is_error(resp)
    assert "file not found" in _error_text(resp)


# ---------------------------------------------------------------------------
# download_pdf
# ---------------------------------------------------------------------------


def test_download_pdf_passes_arguments(with_creds: MagicMock):
    with_creds.download_attachment.return_value = {
        "ok": True,
        "path": "/tmp/x/y.pdf",
        "filename": "y.pdf",
        "bytes": 123,
        "attachment_key": "ATT",
    }
    resp = _call(
        "tools/call",
        {
            "name": "download_pdf",
            "arguments": {
                "item_key": "PARENT",
                "dest_dir": "/tmp/x",
                "filename": "y",
            },
        },
    )
    assert not _is_error(resp)
    assert _structured(resp)["filename"] == "y.pdf"
    with_creds.download_attachment.assert_called_once_with(
        "PARENT", "/tmp/x", filename="y"
    )


def test_download_pdf_rejects_missing_item_key(with_creds):
    resp = _call(
        "tools/call",
        {"name": "download_pdf", "arguments": {"dest_dir": "/tmp"}},
    )
    assert _is_error(resp)
    assert "item_key" in _error_text(resp)


def test_download_pdf_rejects_missing_dest_dir(with_creds):
    resp = _call(
        "tools/call",
        {"name": "download_pdf", "arguments": {"item_key": "K"}},
    )
    assert _is_error(resp)
    assert "dest_dir" in _error_text(resp)


def test_download_pdf_propagates_client_failure(with_creds: MagicMock):
    with_creds.download_attachment.return_value = {
        "ok": False,
        "error": "no PDF attachment child",
    }
    resp = _call(
        "tools/call",
        {
            "name": "download_pdf",
            "arguments": {"item_key": "K", "dest_dir": "/tmp/x"},
        },
    )
    assert _is_error(resp)
    assert "no PDF attachment child" in _error_text(resp)


# ---------------------------------------------------------------------------
# 错误路径
# ---------------------------------------------------------------------------


def test_unknown_tool_returns_isError(with_creds):
    resp = _call("tools/call", {"name": "nonexistent", "arguments": {}})
    assert _is_error(resp)
    assert "未知工具" in _error_text(resp)


def test_unsupported_method_returns_jsonrpc_error():
    # initialize / tools/list / tools/call 之外的 method → JSON-RPC -32601
    # 我们没有 _handle 别的 method，但 main_loop 走 -32601；测试帮手只调三个 handler，
    # 所以这里直接验证 _error 构造
    err = mcp_server._error(99, -32601, "method not supported: foo")
    assert err["error"]["code"] == -32601
    assert err["id"] == 99


# ---------------------------------------------------------------------------
# NDJSON 帧 + main loop（轻量 smoke）
# ---------------------------------------------------------------------------


def test_read_message_handles_ndjson_frames():
    stream = io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"initialize"}\n')
    msg = mcp_server._read_message(stream)
    assert msg == {"jsonrpc": "2.0", "id": 1, "method": "initialize"}


def test_read_message_returns_parse_error_on_garbage():
    stream = io.BytesIO(b"not json at all\n")
    msg = mcp_server._read_message(stream)
    assert "__parse_error__" in msg


def test_write_message_appends_newline():
    stream = io.BytesIO()
    mcp_server._write_message(stream, {"a": 1})
    assert stream.getvalue() == b'{"a": 1}\n'


# ---------------------------------------------------------------------------
# default_mcp_config
# ---------------------------------------------------------------------------


def test_default_mcp_config_returns_stdio_entry(tmp_path):
    cfg = mcp_server.default_mcp_config(tmp_path)
    assert mcp_server.DEFAULT_SERVER_KEY in cfg
    entry = cfg[mcp_server.DEFAULT_SERVER_KEY]
    assert entry["type"] == "stdio"
    assert "src.server.integrations.zotero.mcp_server" in entry["args"]
    assert "PYTHONPATH" in entry["env"]


def test_default_mcp_config_disabled_via_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MAMBA_ZOTERO_MCP_DISABLED", "1")
    assert mcp_server.default_mcp_config(tmp_path) == {}
