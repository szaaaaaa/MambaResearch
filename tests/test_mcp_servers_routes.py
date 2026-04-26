"""MCP servers HTTP routes 测试（Stage 3 Task 1）。

挂 router 到一个独立 FastAPI app，验证四个端点返回与 registry/probe 一致的形状。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.routes.mcp_servers import router as mcp_router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(mcp_router)
    return TestClient(app)


def test_get_servers_returns_at_least_two_builtin(client: TestClient):
    resp = client.get("/api/mcp/servers")
    assert resp.status_code == 200
    body = resp.json()
    names = [s["name"] for s in body["servers"]]
    assert "research_agent" in names
    assert "mamba_workspace" in names


def test_get_server_detail_for_workspace(client: TestClient):
    resp = client.get("/api/mcp/servers/mamba_workspace")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "mamba_workspace"
    assert body["transport"] == "stdio"
    assert "builtin_helper" in body["sources"]


def test_get_server_detail_404_for_missing(client: TestClient):
    resp = client.get("/api/mcp/servers/no-such-server")
    assert resp.status_code == 404


def test_get_server_tools_runs_real_probe(client: TestClient, tmp_path, monkeypatch):
    """probe 端点真起子进程；workspace MCP 需要 MAMBA env 才能 stats，但 tools/list
    本身不依赖 active project（只返回 schema）。这里跑端到端确认形状。"""
    monkeypatch.setenv("MAMBA_ACTIVE_PROJECT_PATH", str(tmp_path))
    resp = client.get("/api/mcp/servers/mamba_workspace/tools")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["server_name"] == "mamba_workspace"
    names = sorted(t["name"] for t in body["tools"])
    assert names == ["classify_one", "list", "scan", "set_user_override", "stats"]
