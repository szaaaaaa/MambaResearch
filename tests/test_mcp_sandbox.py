"""MCP sandbox 直调测试（Stage 3 Task 3）。

策略：跑真实 ``python -m src.server.workspace.mcp_server`` subprocess + 调
``stats`` / ``scan`` 这种安全只读 tool。这同时也是 Task 3 与 Stage 2 入口的
回归保护。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.mcp.models import McpServerInfo
from src.server.mcp.sandbox import DANGEROUS_TOOLS, call_tool
from src.server.mcp.call_logger import McpCallLogger, set_call_logger_for_tests
from src.server.projects.db import MambaDb, set_db_for_tests
from src.server.routes.mcp_servers import router as mcp_router
from src.server.workspace.mcp_server import default_mcp_config


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _workspace_server() -> McpServerInfo:
    raw = default_mcp_config(_REPO_ROOT)["mamba_workspace"]
    return McpServerInfo(
        name="mamba_workspace",
        transport="stdio",
        sources=["builtin_helper"],
        config_paths=["<programmatic>"],
        command=raw["command"],
        args=raw["args"],
        env=raw.get("env", {}),
    )


@pytest.fixture
def db(tmp_path: Path) -> MambaDb:
    instance = MambaDb(db_path=tmp_path / "mamba.db")
    instance.connect()
    set_db_for_tests(instance)
    set_call_logger_for_tests(McpCallLogger(db=instance))
    yield instance
    set_call_logger_for_tests(None)
    set_db_for_tests(None)


@pytest.fixture
def client(db: MambaDb):
    app = FastAPI()
    app.include_router(mcp_router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# call_tool 直接调用
# ---------------------------------------------------------------------------


def test_call_tool_stats_returns_buckets(tmp_path: Path):
    server = _workspace_server()
    result = asyncio.run(
        call_tool(
            server,
            "stats",
            {},
            timeout_s=10.0,
            extra_env={"MAMBA_ACTIVE_PROJECT_PATH": str(tmp_path)},
        )
    )
    assert result.is_error is False, result.error
    assert isinstance(result.output, dict)
    assert "by_bucket" in result.output


def test_call_tool_unknown_method_returns_is_error(tmp_path: Path):
    server = _workspace_server()
    result = asyncio.run(
        call_tool(
            server,
            "no_such_tool",
            {},
            timeout_s=10.0,
            extra_env={"MAMBA_ACTIVE_PROJECT_PATH": str(tmp_path)},
        )
    )
    # workspace MCP 用 isError=true 返回业务错（不是 JSON-RPC error）
    assert result.is_error is True
    assert result.error and "未知工具" in result.error


# ---------------------------------------------------------------------------
# HTTP 路由
# ---------------------------------------------------------------------------


def test_sandbox_call_endpoint_works(
    client: TestClient, tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("MAMBA_ACTIVE_PROJECT_PATH", str(tmp_path))
    resp = client.post(
        "/api/mcp/sandbox/call",
        json={"server_name": "mamba_workspace", "tool_name": "stats", "input": {}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_error"] is False
    assert "call_id" in body
    # mcp_calls 表里应有一条 sandbox 记录
    list_resp = client.get(
        "/api/mcp/calls",
        params={"server_name": "mamba_workspace", "tool_name": "stats"},
    )
    # 此 client 没注册 mcp_calls_router；直接通过 logger 读
    from src.server.mcp.call_logger import get_call_logger

    calls = get_call_logger().list_calls(server_name="mamba_workspace", tool_name="stats")
    assert len(calls) == 1
    assert calls[0]["backend"] == "sandbox"


def test_sandbox_call_unknown_server_returns_404(client: TestClient):
    resp = client.post(
        "/api/mcp/sandbox/call",
        json={"server_name": "ghost", "tool_name": "x", "input": {}},
    )
    assert resp.status_code == 404


def test_sandbox_call_dangerous_requires_confirm(
    client: TestClient, tmp_path: Path, monkeypatch
):
    """临时把 stats 标记为 dangerous，验证 need_confirm 流程。"""
    monkeypatch.setenv("MAMBA_ACTIVE_PROJECT_PATH", str(tmp_path))
    DANGEROUS_TOOLS.add(("mamba_workspace", "stats"))
    try:
        resp = client.post(
            "/api/mcp/sandbox/call",
            json={"server_name": "mamba_workspace", "tool_name": "stats", "input": {}},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["detail"]["code"] == "need_confirm"

        # confirm=True 后放行
        resp_ok = client.post(
            "/api/mcp/sandbox/call",
            json={
                "server_name": "mamba_workspace",
                "tool_name": "stats",
                "input": {},
                "confirm": True,
            },
        )
        assert resp_ok.status_code == 200, resp_ok.text
    finally:
        DANGEROUS_TOOLS.discard(("mamba_workspace", "stats"))


def test_sandbox_call_invalid_body_400(client: TestClient):
    resp = client.post(
        "/api/mcp/sandbox/call",
        json={"server_name": "", "tool_name": "stats", "input": {}},
    )
    assert resp.status_code == 400
    resp = client.post(
        "/api/mcp/sandbox/call",
        json={"server_name": "x", "tool_name": "y", "input": "not a dict"},
    )
    assert resp.status_code == 400
