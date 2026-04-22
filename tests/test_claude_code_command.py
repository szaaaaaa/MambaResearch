"""Claude Code 会话命令端点测试（Task 6b）。

覆盖 ``POST /api/claude-code/sessions/{id}/command`` 的三条命令：

- ``clear``: 重建 SDK client（同 session id），旧 client disconnect + 新 client connect
- ``exit``: 等价 DELETE（断开并移除）
- ``add-dir``: 路径校验 → 追加到 session.add_dirs → 重建 client

真实 SDK 连接需要凭据与子进程，沿用 test_claude_code_session 的 ``fake_sdk``
fixture 把 ``ClaudeSDKClient`` monkeypatch 为内存版 FakeClient，只验证管理器
与路由的分派 / 校验 / 生命周期语义。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

import app as app_module
import src.server.claude_code.session_manager as sm_module


class FakeClient:
    """内存版 ClaudeSDKClient，仅实现会被用到的方法。"""

    created: list["FakeClient"] = []

    def __init__(self, options):
        self.options = options
        self.connected = False
        self.disconnected = False
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


@pytest.fixture
def fake_sdk(monkeypatch):
    FakeClient.created = []
    monkeypatch.setattr(sm_module, "ClaudeSDKClient", FakeClient)
    monkeypatch.setattr(sm_module.session_manager, "_sessions", {})
    monkeypatch.setattr(sm_module.session_manager, "_lock", asyncio.Lock())
    yield FakeClient


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


def test_command_clear_rebuilds_client(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        # 创建会话触发第 1 次 FakeClient 实例化
        assert len(FakeClient.created) == 1
        first = FakeClient.created[0]
        assert first.connected is True and first.disconnected is False

        resp = client.post(
            f"/api/claude-code/sessions/{sid}/command", json={"command": "clear"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "cleared"
        # session id 不变
        assert body["session"]["id"] == sid

        # 旧 client disconnect + 新 client connect
        assert len(FakeClient.created) == 2
        assert first.disconnected is True
        second = FakeClient.created[1]
        assert second.connected is True
        # add_dirs 空会话 clear 后仍空
        assert body["session"]["add_dirs"] == []
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_command_clear_unknown_session_returns_404(fake_sdk):
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/claude-code/sessions/missing/command", json={"command": "clear"}
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# exit
# ---------------------------------------------------------------------------


def test_command_exit_disconnects_and_removes(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]

    resp = client.post(
        f"/api/claude-code/sessions/{sid}/command", json={"command": "exit"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "exited", "id": sid}

    # 已从列表移除
    listed = client.get("/api/claude-code/sessions").json()["sessions"]
    assert all(s["id"] != sid for s in listed)
    # client disconnect 调用
    assert FakeClient.created[0].disconnected is True


def test_command_exit_unknown_session_returns_404(fake_sdk):
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/claude-code/sessions/missing/command", json={"command": "exit"}
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# add-dir
# ---------------------------------------------------------------------------


def test_command_add_dir_appends_and_rebuilds(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        # 项目根下确定存在的子目录
        resp = client.post(
            f"/api/claude-code/sessions/{sid}/command",
            json={"command": "add-dir", "args": {"path": "src"}},
        )
        assert resp.status_code == 200, resp.json()
        body = resp.json()
        assert body["status"] == "added"
        # add_dirs 含解析后的绝对路径（与 cwd 同级、在项目根下）
        dirs = body["session"]["add_dirs"]
        assert len(dirs) == 1
        assert dirs[0].endswith("src") or dirs[0].endswith("src\\") or dirs[0].endswith("src/")

        # 重建路径：2 个 FakeClient 实例，旧的 disconnected
        assert len(FakeClient.created) == 2
        assert FakeClient.created[0].disconnected is True
        # 新 client 的 options.add_dirs 含该路径
        new_opts = FakeClient.created[1].options
        assert dirs[0] in list(getattr(new_opts, "add_dirs", []))
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_command_add_dir_is_idempotent(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        client.post(
            f"/api/claude-code/sessions/{sid}/command",
            json={"command": "add-dir", "args": {"path": "src"}},
        )
        # 重复追加同一目录不应再重建 client
        before = len(FakeClient.created)
        resp = client.post(
            f"/api/claude-code/sessions/{sid}/command",
            json={"command": "add-dir", "args": {"path": "src"}},
        )
        assert resp.status_code == 200
        assert resp.json()["session"]["add_dirs"] == resp.json()["session"]["add_dirs"]
        assert len(FakeClient.created) == before
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_command_add_dir_requires_path(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        resp = client.post(
            f"/api/claude-code/sessions/{sid}/command",
            json={"command": "add-dir", "args": {}},
        )
        assert resp.status_code == 400
        assert "path" in resp.json()["detail"]
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_command_add_dir_rejects_path_outside_root(fake_sdk, tmp_path):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        # tmp_path 由 pytest 提供，在项目根之外
        resp = client.post(
            f"/api/claude-code/sessions/{sid}/command",
            json={"command": "add-dir", "args": {"path": str(tmp_path)}},
        )
        assert resp.status_code == 400
        assert "project root" in resp.json()["detail"]
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_command_add_dir_rejects_nonexistent_path(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        resp = client.post(
            f"/api/claude-code/sessions/{sid}/command",
            json={"command": "add-dir", "args": {"path": "no-such-dir-xyz"}},
        )
        assert resp.status_code == 400
        assert "does not exist" in resp.json()["detail"]
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


# ---------------------------------------------------------------------------
# 总体校验
# ---------------------------------------------------------------------------


def test_command_unknown_returns_400(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        resp = client.post(
            f"/api/claude-code/sessions/{sid}/command",
            json={"command": "foobar"},
        )
        assert resp.status_code == 400
        assert "unknown command" in resp.json()["detail"]
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_command_missing_command_returns_400(fake_sdk):
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        resp = client.post(f"/api/claude-code/sessions/{sid}/command", json={})
        assert resp.status_code == 400
        assert "command is required" in resp.json()["detail"]
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_command_clear_preserves_add_dirs(fake_sdk):
    """clear 只清上下文，不该重置 add_dirs（用户的工作区配置）。"""
    client = TestClient(app_module.app)
    sid = client.post("/api/claude-code/sessions", json={}).json()["id"]
    try:
        # 先追加目录
        r1 = client.post(
            f"/api/claude-code/sessions/{sid}/command",
            json={"command": "add-dir", "args": {"path": "src"}},
        )
        added_dirs = r1.json()["session"]["add_dirs"]
        assert len(added_dirs) == 1

        # 然后 clear
        r2 = client.post(
            f"/api/claude-code/sessions/{sid}/command", json={"command": "clear"}
        )
        assert r2.status_code == 200
        assert r2.json()["session"]["add_dirs"] == added_dirs
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")
