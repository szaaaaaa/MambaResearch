"""MCP server config CRUD 测试（Stage 3 Task 4）。

所有测试用 ``repo_root=tmp_path``，永不污染真实 .mcp.json。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.server.mcp.config_io import (
    McpConfigConflict,
    McpConfigError,
    McpConfigForbidden,
    add_custom_server,
    delete_custom_server,
    list_custom_servers,
)


def test_list_custom_returns_empty_when_no_file(tmp_path: Path):
    assert list_custom_servers(repo_root=tmp_path) == {}


def test_add_stdio_server_creates_file(tmp_path: Path):
    item = add_custom_server(
        {
            "name": "filesystem",
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        },
        repo_root=tmp_path,
    )
    assert item["name"] == "filesystem"
    assert item["type"] == "stdio"
    assert item["command"] == "npx"
    # 文件落地
    saved = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert "filesystem" in saved["mcpServers"]


def test_add_http_server_requires_url(tmp_path: Path):
    with pytest.raises(McpConfigError, match="必须给 url"):
        add_custom_server(
            {"name": "remote", "transport": "http"},
            repo_root=tmp_path,
        )


def test_add_stdio_requires_command(tmp_path: Path):
    with pytest.raises(McpConfigError, match="必须给 command"):
        add_custom_server({"name": "x", "transport": "stdio"}, repo_root=tmp_path)


def test_invalid_transport_rejected(tmp_path: Path):
    with pytest.raises(McpConfigError, match="transport 必须"):
        add_custom_server(
            {"name": "x", "transport": "carrier-pigeon"},
            repo_root=tmp_path,
        )


def test_builtin_name_forbidden(tmp_path: Path):
    with pytest.raises(McpConfigForbidden):
        add_custom_server(
            {"name": "mamba_workspace", "transport": "stdio", "command": "fake"},
            repo_root=tmp_path,
        )


def test_duplicate_name_conflict(tmp_path: Path):
    add_custom_server(
        {"name": "x", "transport": "stdio", "command": "echo"},
        repo_root=tmp_path,
    )
    with pytest.raises(McpConfigConflict):
        add_custom_server(
            {"name": "x", "transport": "stdio", "command": "echo"},
            repo_root=tmp_path,
        )


def test_delete_existing_server(tmp_path: Path):
    add_custom_server(
        {"name": "x", "transport": "stdio", "command": "echo"},
        repo_root=tmp_path,
    )
    delete_custom_server("x", repo_root=tmp_path)
    assert list_custom_servers(repo_root=tmp_path) == {}


def test_delete_missing_server_raises_conflict(tmp_path: Path):
    # 用 conflict 是因为 routes 把它映射成 404；这里仅验异常类型
    with pytest.raises(McpConfigConflict):
        delete_custom_server("ghost", repo_root=tmp_path)


def test_delete_builtin_forbidden(tmp_path: Path):
    with pytest.raises(McpConfigForbidden):
        delete_custom_server("mamba_workspace", repo_root=tmp_path)


def test_env_validation(tmp_path: Path):
    # 合法 env
    add_custom_server(
        {
            "name": "x1",
            "transport": "stdio",
            "command": "py",
            "env": {"FOO": "bar"},
        },
        repo_root=tmp_path,
    )
    # 非 string→string env 拒绝
    with pytest.raises(McpConfigError, match="env"):
        add_custom_server(
            {
                "name": "x2",
                "transport": "stdio",
                "command": "py",
                "env": {"FOO": 123},
            },
            repo_root=tmp_path,
        )


def test_corrupt_mcp_json_raises(tmp_path: Path):
    (tmp_path / ".mcp.json").write_text("not json", encoding="utf-8")
    with pytest.raises(McpConfigError, match="损坏"):
        add_custom_server(
            {"name": "x", "transport": "stdio", "command": "echo"},
            repo_root=tmp_path,
        )
