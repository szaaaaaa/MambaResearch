"""MCP probe 测试（Stage 3 Task 1）。

不 mock subprocess——用真实 ``python -m src.server.workspace.mcp_server`` 跑探活，
验证 stdio NDJSON 协议握手能拿到 5 个工具。这同时是 Stage 2 entry 的回归保护。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.server.mcp.models import McpServerInfo
from src.server.mcp.probe import probe_server
from src.server.workspace.mcp_server import default_mcp_config


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _workspace_server() -> McpServerInfo:
    config = default_mcp_config(_REPO_ROOT)
    raw = config["mamba_workspace"]
    return McpServerInfo(
        name="mamba_workspace",
        transport="stdio",
        sources=["builtin_helper"],
        config_paths=["<programmatic>"],
        command=raw["command"],
        args=raw["args"],
        env=raw.get("env", {}),
    )


def test_probe_workspace_server_returns_running(tmp_path: Path):
    server = _workspace_server()
    status = asyncio.run(
        probe_server(
            server,
            timeout_s=10.0,
            extra_env={"MAMBA_ACTIVE_PROJECT_PATH": str(tmp_path)},
        )
    )
    assert status.status == "running", f"probe failed: {status.error}"
    # workspace MCP 暴露 5 个工具
    assert status.tools_count == 5
    names = sorted(t.name for t in status.tools)
    assert names == ["classify_one", "list", "scan", "set_user_override", "stats"]


def test_probe_unknown_command_returns_error(tmp_path: Path):
    server = McpServerInfo(
        name="ghost",
        transport="stdio",
        command="this-binary-does-not-exist-mamba-test",
        args=[],
    )
    status = asyncio.run(probe_server(server, timeout_s=2.0))
    assert status.status == "error"
    assert status.error is not None


def test_probe_http_transport_returns_error(tmp_path: Path):
    """Stage 3 Task 1 仅实现 stdio probe；http/sse 应返 error 而非 silently 假成功。"""
    server = McpServerInfo(
        name="some-http-server",
        transport="http",
        url="http://localhost:9999",
    )
    status = asyncio.run(probe_server(server, timeout_s=2.0))
    assert status.status == "error"
    assert status.error and "stdio" in status.error
