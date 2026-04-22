"""Claude Code 会话配置端点测试（Task 6c）。

覆盖：

- ``PATCH /api/claude-code/sessions/{id}``：model / permission_mode 单字段 / 双字段
- ``GET   /api/claude-code/sessions/{id}/mcp``：MCP 挂载状态
- ``GET   /api/claude-code/models``：模型白名单

真实 SDK 需要凭据与子进程，沿用 test_claude_code_session 的 fake_sdk 思路，但在
FakeClient 上多实现 ``set_model`` / ``set_permission_mode`` / ``get_mcp_status``
三个 SDK 运行时方法。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

import app as app_module
import src.server.claude_code.session_manager as sm_module


class FakeClient:
    """内存版 ClaudeSDKClient，覆盖 6c 用到的 SDK 运行时方法。"""

    created: list["FakeClient"] = []

    def __init__(self, options):
        self.options = options
        self.connected = False
        self.disconnected = False
        self.model_calls: list[str | None] = []
        self.permission_mode_calls: list[str] = []
        self.mcp_status_payload: dict[str, object] = {"mcpServers": []}
        FakeClient.created.append(self)

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.disconnected = True

    async def query(self, prompt, session_id="default"):  # pragma: no cover - 未用
        pass

    async def receive_response(self):  # pragma: no cover - 未用
        if False:
            yield None

    async def interrupt(self):  # pragma: no cover - 未用
        pass

    async def set_model(self, model):
        self.model_calls.append(model)

    async def set_permission_mode(self, mode):
        self.permission_mode_calls.append(mode)

    async def get_mcp_status(self):
        return self.mcp_status_payload


@pytest.fixture
def fake_sdk(monkeypatch):
    FakeClient.created = []
    monkeypatch.setattr(sm_module, "ClaudeSDKClient", FakeClient)
    monkeypatch.setattr(sm_module.session_manager, "_sessions", {})
    monkeypatch.setattr(sm_module.session_manager, "_lock", asyncio.Lock())
    yield FakeClient


# ---------------------------------------------------------------------------
# PATCH model
# ---------------------------------------------------------------------------


def test_patch_updates_model(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        resp = client.patch(
            f"/api/claude-code/sessions/{sid}",
            json={"model": "claude-opus-4-7"},
        )
        assert resp.status_code == 200, resp.json()
        body = resp.json()
        assert body["status"] == "updated"
        assert body["session"]["model"] == "claude-opus-4-7"

        # 未重建 client（只有一个 FakeClient 实例），SDK set_model 被调用
        assert len(FakeClient.created) == 1
        assert FakeClient.created[0].model_calls == ["claude-opus-4-7"]
        assert FakeClient.created[0].disconnected is False
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_patch_model_null_resets(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post(
        "/api/claude-code/sessions", json={"model": "claude-opus-4-7"}
    ).json()["id"]
    try:
        resp = client.patch(
            f"/api/claude-code/sessions/{sid}", json={"model": None}
        )
        assert resp.status_code == 200
        assert resp.json()["session"]["model"] is None
        assert FakeClient.created[0].model_calls == [None]
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_patch_rejects_unknown_model(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        resp = client.patch(
            f"/api/claude-code/sessions/{sid}", json={"model": "gpt-5"}
        )
        assert resp.status_code == 400
        assert "invalid model" in resp.json()["detail"]
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


# ---------------------------------------------------------------------------
# PATCH permission_mode
# ---------------------------------------------------------------------------


def test_patch_updates_permission_mode(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        resp = client.patch(
            f"/api/claude-code/sessions/{sid}",
            json={"permission_mode": "acceptEdits"},
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["session"]["permission_mode"] == "acceptEdits"

        assert FakeClient.created[0].permission_mode_calls == ["acceptEdits"]
        # 运行时切换不销毁 client
        assert FakeClient.created[0].disconnected is False
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_patch_rejects_invalid_mode(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        resp = client.patch(
            f"/api/claude-code/sessions/{sid}", json={"permission_mode": "strict"}
        )
        assert resp.status_code == 400
        assert "invalid permission_mode" in resp.json()["detail"]
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


# ---------------------------------------------------------------------------
# PATCH 边界
# ---------------------------------------------------------------------------


def test_patch_requires_at_least_one_field(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        resp = client.patch(f"/api/claude-code/sessions/{sid}", json={})
        assert resp.status_code == 400
        assert "at least one of" in resp.json()["detail"]
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_patch_applies_both_fields(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        resp = client.patch(
            f"/api/claude-code/sessions/{sid}",
            json={"model": "claude-sonnet-4-6", "permission_mode": "plan"},
        )
        assert resp.status_code == 200
        body = resp.json()["session"]
        assert body["model"] == "claude-sonnet-4-6"
        assert body["permission_mode"] == "plan"

        client_inst = FakeClient.created[0]
        assert client_inst.model_calls == ["claude-sonnet-4-6"]
        assert client_inst.permission_mode_calls == ["plan"]
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_patch_unknown_session_returns_404(fake_sdk):
    client = TestClient(app_module.app)
    resp = client.patch(
        "/api/claude-code/sessions/missing",
        json={"permission_mode": "default"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /mcp
# ---------------------------------------------------------------------------


def test_get_mcp_returns_sdk_payload(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        # 预置挂载的 server
        FakeClient.created[0].mcp_status_payload = {
            "mcpServers": [
                {"name": "paper_search", "status": "connected"},
                {"name": "filesystem", "status": "failed"},
            ]
        }
        resp = client.get(f"/api/claude-code/sessions/{sid}/mcp")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["mcpServers"]) == 2
        assert body["mcpServers"][0]["name"] == "paper_search"
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_get_mcp_empty_list(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        resp = client.get(f"/api/claude-code/sessions/{sid}/mcp")
        assert resp.status_code == 200
        assert resp.json() == {"mcpServers": []}
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_get_mcp_unknown_session_returns_404(fake_sdk):
    client = TestClient(app_module.app)
    resp = client.get("/api/claude-code/sessions/missing/mcp")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /models
# ---------------------------------------------------------------------------


def test_list_models_returns_whitelist(fake_sdk):
    client = TestClient(app_module.app)
    resp = client.get("/api/claude-code/models")
    assert resp.status_code == 200
    body = resp.json()
    assert "models" in body
    ids = [m["id"] for m in body["models"]]
    assert "claude-opus-4-7" in ids
    assert "claude-sonnet-4-6" in ids
    # 每个条目都带 label 给 UI 展示用
    assert all("label" in m for m in body["models"])
