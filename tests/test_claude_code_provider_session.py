"""Session provider 注入测试（Task 1b）。

覆盖 acceptance：
1. POST /sessions 接受 `provider` 字段，非空时按 registry 查表注入 env；未传零变更
2. SDK 子进程 env 含 ANTHROPIC_BASE_URL 指向 registry 的 base_url
3. GET /sessions/{id} 返回 provider 名，不回传 api_key
4. 现有 HITL / MCP / slash / 持久化 pytest 全部通过（本测试与 test_claude_code_session 共存）
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

import src.server.claude_code.providers as providers_mod
import src.server.claude_code.session_manager as sm_module

import app as app_module


# ---------------------------------------------------------------------------
# 假 SDK 客户端 —— 暴露 options 供断言 env 注入
# ---------------------------------------------------------------------------


class FakeClient:
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

    async def query(self, prompt, session_id="default"):  # pragma: no cover
        pass

    async def receive_response(self):  # pragma: no cover
        if False:
            yield None

    async def interrupt(self):  # pragma: no cover
        pass

    async def set_model(self, model):  # pragma: no cover
        pass

    async def set_permission_mode(self, mode):  # pragma: no cover
        pass

    async def get_mcp_status(self):  # pragma: no cover
        return {"mcpServers": []}


@pytest.fixture
def fake_sdk(monkeypatch):
    FakeClient.created = []
    monkeypatch.setattr(sm_module, "ClaudeSDKClient", FakeClient)
    monkeypatch.setattr(sm_module.session_manager, "_sessions", {})
    monkeypatch.setattr(sm_module.session_manager, "_lock", asyncio.Lock())

    # 注入受控 registry，避免测试依赖真实 agent.yaml 被改动
    test_registry = {
        "anthropic": providers_mod.ProviderConfig(
            name="anthropic",
            base_url="https://api.anthropic.com",
            api_key_env="ANTHROPIC_API_KEY",
            default_model="",
        ),
        "deepseek": providers_mod.ProviderConfig(
            name="deepseek",
            base_url="http://localhost:3456",
            api_key_env="ANTHROPIC_API_KEY",
            default_model="deepseek-chat",
        ),
    }
    providers_mod.reset_provider_registry_cache()
    monkeypatch.setattr(providers_mod, "_cached_registry", test_registry)
    # 保证 api_key_env 有值
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key-abc")
    yield FakeClient
    providers_mod.reset_provider_registry_cache()


# ---------------------------------------------------------------------------
# AC1: provider 字段接受与零变更路径
# ---------------------------------------------------------------------------


def test_post_without_provider_uses_default_no_env_override(fake_sdk):
    """未传 provider → ClaudeAgentOptions.env 未被设置（Anthropic 默认路径）。"""
    client = TestClient(app_module.app)
    resp = client.post("/api/claude-code/sessions", json={})
    assert resp.status_code == 200
    sid = resp.json()["id"]
    try:
        # options.env 应该未被设置（或为 None）
        options = FakeClient.created[-1].options
        # SDK options 可能把 env 默认为 None 或不设——两种都接受
        env = getattr(options, "env", None)
        assert not env, f"expected no env override, got {env!r}"
        # response body provider 为 None
        assert resp.json()["provider"] is None
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_post_with_provider_injects_registry_env(fake_sdk):
    """传 provider=deepseek → options.env 含 ANTHROPIC_BASE_URL 指向 registry base_url。"""
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/claude-code/sessions", json={"provider": "deepseek"}
    )
    assert resp.status_code == 200
    sid = resp.json()["id"]
    try:
        options = FakeClient.created[-1].options
        env = getattr(options, "env", None)
        assert env is not None, "env override missing"
        # AC2: ANTHROPIC_BASE_URL 指向 registry 的 base_url
        assert env["ANTHROPIC_BASE_URL"] == "http://localhost:3456"
        # api_key 从 os.environ 解析
        assert env["ANTHROPIC_API_KEY"] == "sk-test-key-abc"
        # response 回显 provider 名
        assert resp.json()["provider"] == "deepseek"
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


def test_post_unknown_provider_returns_400(fake_sdk):
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/claude-code/sessions", json={"provider": "ghost-provider"}
    )
    assert resp.status_code == 400
    assert "unknown provider" in resp.json()["detail"]
    # 没有任何 SDK client 被构造
    assert FakeClient.created == []


def test_post_provider_non_string_returns_400(fake_sdk):
    client = TestClient(app_module.app)
    resp = client.post("/api/claude-code/sessions", json={"provider": 42})
    assert resp.status_code == 400
    assert "non-empty string" in resp.json()["detail"]


def test_post_provider_empty_string_returns_400(fake_sdk):
    client = TestClient(app_module.app)
    resp = client.post("/api/claude-code/sessions", json={"provider": "   "})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# AC3: GET 响应不漏 api_key
# ---------------------------------------------------------------------------


def test_session_response_never_contains_api_key(fake_sdk):
    """POST 响应 + GET /sessions 列表都不应出现 api_key 或 sk-test。"""
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/claude-code/sessions", json={"provider": "deepseek"}
    )
    body = resp.json()
    sid = body["id"]
    try:
        # POST 响应检查
        flat = str(body).lower()
        assert "api_key" not in flat
        assert "sk-test-key" not in flat

        # GET 列表检查
        listed = client.get("/api/claude-code/sessions").json()
        flat = str(listed).lower()
        assert "api_key" not in flat
        assert "sk-test-key" not in flat

        # 列表条目应含 provider 字段
        matching = [s for s in listed["sessions"] if s["id"] == sid]
        assert len(matching) == 1
        assert matching[0].get("provider") == "deepseek"
    finally:
        client.delete(f"/api/claude-code/sessions/{sid}")


# ---------------------------------------------------------------------------
# 缺 api_key 时显式报错，不静默
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1c: GET /api/claude-code/providers 列表端点
# ---------------------------------------------------------------------------


def test_list_providers_returns_registry_entries(fake_sdk):
    """端点返回 registry 里所有 provider，每条含 name / base_url / default_model。"""
    client = TestClient(app_module.app)
    resp = client.get("/api/claude-code/providers")
    assert resp.status_code == 200
    body = resp.json()
    assert "providers" in body
    names = {p["name"] for p in body["providers"]}
    assert names == {"anthropic", "deepseek"}

    # 结构检查
    for p in body["providers"]:
        assert set(p.keys()) == {"name", "base_url", "default_model"}
    deepseek = next(p for p in body["providers"] if p["name"] == "deepseek")
    assert deepseek["base_url"] == "http://localhost:3456"
    assert deepseek["default_model"] == "deepseek-chat"


def test_list_providers_never_leaks_api_key_fields(fake_sdk):
    """响应不应出现 api_key / api_key_env / secret 等敏感字段。"""
    client = TestClient(app_module.app)
    resp = client.get("/api/claude-code/providers")
    flat = str(resp.json()).lower()
    assert "api_key" not in flat
    assert "secret" not in flat
    # 也不漏 api_key_env 字段名本身
    assert "api_key_env" not in flat


def test_list_providers_empty_registry_returns_empty_list(fake_sdk, monkeypatch):
    """registry 为空时返回 ``{"providers": []}``，不 500。"""
    monkeypatch.setattr(providers_mod, "_cached_registry", {})
    client = TestClient(app_module.app)
    resp = client.get("/api/claude-code/providers")
    assert resp.status_code == 200
    assert resp.json() == {"providers": []}


# ---------------------------------------------------------------------------
# 其他负面测试
# ---------------------------------------------------------------------------


def test_missing_api_key_env_errors_explicitly(fake_sdk, monkeypatch):
    """provider 的 api_key_env 对应 env 未设置 → 显式报错（不静默走 default）。

    路由层把 ``ValueError``（``ProviderRegistryError`` 继承自它）映射为 400，
    消息里必须提到缺失的 env 名，便于用户立即定位。
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = TestClient(app_module.app)
    resp = client.post(
        "/api/claude-code/sessions", json={"provider": "deepseek"}
    )
    assert resp.status_code == 400
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]
