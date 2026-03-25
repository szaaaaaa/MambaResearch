from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.parse

import pytest

from src.common import openai_codex as openai_codex_module
from src.dynamic_os.contracts.policy import BudgetPolicy, PermissionPolicy
from src.dynamic_os.contracts.skill_spec import SkillPermissions
from src.dynamic_os.policy.engine import BudgetExceededError, PolicyEngine, PolicyViolationError
from src.dynamic_os.tools import backends as backends_module
from src.dynamic_os.tools.backends import ConfiguredLLMClient
from src.dynamic_os.tools.discovery import start_mcp_runtime
from src.dynamic_os.tools.gateway import ToolGateway
from src.dynamic_os.tools.registry import ToolCapability, ToolRegistry


def test_tool_registry_normalizes_mcp_tools() -> None:
    registry = ToolRegistry.from_servers(
        [
            {
                "server_id": "search",
                "tools": [
                    {"name": "arxiv", "capability": "search"},
                    {"name": "semantic-scholar", "capability": "search"},
                ],
            }
        ]
    )

    assert [tool.tool_id for tool in registry.list()] == [
        "mcp.search.arxiv",
        "mcp.search.semantic_scholar",
    ]
    assert registry.resolve(ToolCapability.search, preferred="arxiv").tool_id == "mcp.search.arxiv"

def test_dynamic_runtime_discovers_tools_from_configured_mcp_servers() -> None:
    async def run_case() -> None:
        runtime = await start_mcp_runtime(
            [
                {
                    "server_id": "llm",
                    "command": [
                        "${python}",
                        "${workspace_root}/scripts/dynamic_os_mcp_server.py",
                        "--root",
                        "${workspace_root}",
                        "--server-id",
                        "llm",
                    ],
                },
                {
                    "server_id": "search",
                    "command": [
                        "${python}",
                        "${workspace_root}/scripts/dynamic_os_mcp_server.py",
                        "--root",
                        "${workspace_root}",
                        "--server-id",
                        "search",
                    ],
                },
                {
                    "server_id": "retrieval",
                    "command": [
                        "${python}",
                        "${workspace_root}/scripts/dynamic_os_mcp_server.py",
                        "--root",
                        "${workspace_root}",
                        "--server-id",
                        "retrieval",
                    ],
                },
            ],
            root=Path.cwd(),
        )
        try:
            assert [tool.tool_id for tool in runtime.registry.list()] == [
                "mcp.llm.chat",
                "mcp.retrieval.indexer",
                "mcp.retrieval.store",
                "mcp.search.papers",
            ]
            assert all(snapshot["command"] for snapshot in runtime.snapshot)
        finally:
            await runtime.close()

    asyncio.run(run_case())


def test_policy_engine_blocks_commands_and_config_writes() -> None:
    workspace = Path.cwd()
    engine = PolicyEngine(
        permission_policy=PermissionPolicy(approved_workspaces=[str(workspace)]),
    )

    engine.assert_path_allowed(workspace / "README.md", operation="read")

    with pytest.raises(PolicyViolationError, match="blocked command"):
        engine.assert_command_allowed("git reset --hard HEAD")

    with pytest.raises(PolicyViolationError, match="blocked command"):
        engine.assert_command_allowed("Remove-Item -Path target -Recurse -Force")

    with pytest.raises(PolicyViolationError, match="blocked command"):
        engine.assert_command_allowed('powershell -Command "Remove-Item -Path target -Recurse -Force"')

    with pytest.raises(PolicyViolationError, match="config overwrite is blocked"):
        engine.assert_path_allowed(workspace / "configs" / "agent.yaml", operation="write")


def test_policy_engine_enforces_budget_limit() -> None:
    engine = PolicyEngine(
        budget_policy=BudgetPolicy(max_tool_invocations=1),
        permission_policy=PermissionPolicy(),
    )

    engine.record_tool_invocation()

    with pytest.raises(BudgetExceededError, match="工具调用次数已超出预算"):
        engine.record_tool_invocation()


def test_tool_gateway_search_uses_registry_and_policy() -> None:
    registry = ToolRegistry.from_servers(
        [
            {
                "server_id": "search",
                "tools": [
                    {"name": "arxiv", "capability": "search"},
                ],
            }
        ]
    )
    engine = PolicyEngine(
        permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())]),
    )
    calls: list[tuple[str, dict[str, object]]] = []

    async def invoker(tool, payload):
        calls.append((tool.tool_id, payload))
        return {"results": [{"paper_id": "arxiv:2401.00001", "title": "Test Paper", "query": payload["query"]}], "warnings": []}

    gateway = ToolGateway(registry=registry, policy=engine, mcp_invoker=invoker)

    result = asyncio.run(gateway.search("retrieval planning", source="arxiv", max_results=5))

    assert result == {
        "results": [{"paper_id": "arxiv:2401.00001", "title": "Test Paper", "query": "retrieval planning"}],
        "warnings": [],
    }
    assert calls == [
        ("mcp.search.arxiv", {"query": "retrieval planning", "source": "arxiv", "max_results": 5}),
    ]
    assert engine.snapshot()["tool_invocations"] == 1


def test_tool_gateway_rejects_network_when_disabled() -> None:
    registry = ToolRegistry.from_servers(
        [
            {
                "server_id": "search",
                "tools": [
                    {"name": "arxiv", "capability": "search"},
                ],
            }
        ]
    )
    engine = PolicyEngine(
        permission_policy=PermissionPolicy(
            allow_network=False,
            approved_workspaces=[str(Path.cwd())],
        ),
    )
    gateway = ToolGateway(registry=registry, policy=engine, mcp_invoker=lambda tool, payload: [])

    with pytest.raises(PolicyViolationError, match="network access is not allowed"):
        asyncio.run(gateway.search("blocked"))


def test_tool_gateway_scopes_skill_permissions() -> None:
    registry = ToolRegistry.from_servers(
        [
            {
                "server_id": "search",
                "tools": [
                    {"name": "arxiv", "capability": "search"},
                ],
            }
        ]
    )
    engine = PolicyEngine(
        permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())]),
    )
    gateway = ToolGateway(registry=registry, policy=engine, mcp_invoker=lambda tool, payload: [])
    restricted = gateway.with_permissions(SkillPermissions(network=False))

    with pytest.raises(PolicyViolationError, match="skill does not allow network access"):
        asyncio.run(restricted.search("blocked"))


def test_tool_gateway_enforces_allowed_tool_ids() -> None:
    registry = ToolRegistry.from_servers(
        [
            {
                "server_id": "llm",
                "tools": [
                    {"name": "chat", "capability": "llm_chat"},
                ],
            },
            {
                "server_id": "search",
                "tools": [
                    {"name": "arxiv", "capability": "search"},
                ],
            },
        ]
    )
    engine = PolicyEngine(
        permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())]),
    )
    gateway = ToolGateway(registry=registry, policy=engine, mcp_invoker=lambda tool, payload: [])
    restricted = gateway.with_permissions(SkillPermissions(network=True)).with_allowed_tools(["mcp.llm.chat"])

    with pytest.raises(PolicyViolationError, match="tool is not allowed for skill"):
        asyncio.run(restricted.search("blocked"))


def test_configured_llm_client_uses_openai_codex_oauth_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeHttpResponse:
        def __enter__(self) -> "FakeHttpResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def __iter__(self):
            events = [
                {
                    "type": "response.output_text.delta",
                    "delta": "ok",
                },
                {
                    "type": "response.completed",
                    "response": {
                        "output": [
                            {
                                "type": "message",
                                "content": [{"type": "output_text", "text": "ok"}],
                            }
                        ],
                        "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
                    },
                },
            ]
            for event in events:
                yield f"data: {json.dumps(event)}\n".encode("utf-8")
                yield b"\n"

    def fake_urlopen(request, timeout=0):
        assert request.full_url == backends_module.OPENAI_CODEX_RESPONSES_URL
        assert timeout == 120
        headers = {key.lower(): value for key, value in request.header_items()}
        assert headers["authorization"] == "Bearer token"
        assert headers["chatgpt-account-id"] == "acct_123"
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["model"] == "gpt-5.4"
        assert payload["stream"] is True
        assert str(payload["instructions"]).strip()
        assert payload["input"][0]["role"] == "user"
        assert payload["text"]["format"]["type"] == "json_schema"
        return FakeHttpResponse()

    monkeypatch.setattr(
        backends_module,
        "ensure_openai_codex_auth",
        lambda **kwargs: {
            "tokens": {
                "access_token": "token",
                "account_id": "acct_123",
            }
        },
    )
    monkeypatch.setattr(backends_module.urllib.request, "urlopen", fake_urlopen)

    result = ConfiguredLLMClient(
        saved_env={},
        workspace_root=Path.cwd(),
        config={"llm": {"openai_codex": {"transport": "sse"}}},
    ).complete(
        provider="openai_codex",
        model="openai-codex/gpt-5.4",
        messages=[{"role": "user", "content": "reply with ok"}],
        temperature=0.2,
        max_tokens=128,
        response_schema={"type": "object", "properties": {"result": {"type": "string"}}},
    )

    assert result.text == "ok"
    assert result.usage["total_tokens"] == 18


def test_configured_llm_client_rejects_missing_openai_codex_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        backends_module,
        "ensure_openai_codex_auth",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("openai codex oauth is not logged in")),
    )

    client = ConfiguredLLMClient(
        saved_env={},
        workspace_root=Path.cwd(),
        config={"llm": {"openai_codex": {"transport": "sse"}}},
    )

    with pytest.raises(RuntimeError, match="not logged in"):
        client.complete(
            provider="openai_codex",
            model="openai-codex/gpt-5.4",
            messages=[{"role": "user", "content": "reply with ok"}],
            temperature=0.2,
            max_tokens=128,
        )


def test_configured_llm_client_rejects_legacy_openai_codex_bare_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        backends_module,
        "ensure_openai_codex_auth",
        lambda **kwargs: {"tokens": {"access_token": "token", "account_id": "acct_123"}},
    )

    client = ConfiguredLLMClient(
        saved_env={},
        workspace_root=Path.cwd(),
        config={"llm": {"openai_codex": {"transport": "sse"}}},
    )

    with pytest.raises(RuntimeError, match="openai-codex/<model>"):
        client.complete(
            provider="openai_codex",
            model="gpt-5.4",
            messages=[{"role": "user", "content": "reply with ok"}],
            temperature=0.2,
            max_tokens=128,
        )


def test_configured_llm_client_openai_codex_auto_falls_back_to_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        backends_module,
        "ensure_openai_codex_auth",
        lambda **kwargs: {"tokens": {"access_token": "token", "account_id": "acct_123"}},
    )
    monkeypatch.setattr(backends_module, "remember_openai_codex_model", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        ConfiguredLLMClient,
        "_openai_codex_websocket_complete",
        lambda self, **kwargs: (_ for _ in ()).throw(RuntimeError("ws down")),
    )
    monkeypatch.setattr(
        ConfiguredLLMClient,
        "_openai_codex_sse_complete",
        lambda self, **kwargs: backends_module.LLMCompletionResult(
            text="ok-from-sse",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        ),
    )

    client = ConfiguredLLMClient(
        saved_env={},
        workspace_root=Path.cwd(),
        config={"llm": {"openai_codex": {"transport": "auto"}}},
    )

    result = client.complete(
        provider="openai_codex",
        model="openai-codex/gpt-5.1-codex",
        messages=[{"role": "user", "content": "reply with ok"}],
        temperature=0.2,
        max_tokens=32,
    )

    assert result.text == "ok-from-sse"
    assert result.usage["total_tokens"] == 2


def test_configured_llm_client_passes_agent_config_to_openai_codex_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_auth(**kwargs):
        captured.update(kwargs)
        return {"tokens": {"access_token": "token", "account_id": "acct_123"}}

    monkeypatch.setattr(backends_module, "ensure_openai_codex_auth", fake_auth)
    monkeypatch.setattr(backends_module, "remember_openai_codex_model", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        ConfiguredLLMClient,
        "_openai_codex_sse_complete",
        lambda self, **kwargs: backends_module.LLMCompletionResult(
            text="ok",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        ),
    )

    config = {
        "auth": {
            "openai_codex": {
                "default_profile": "work_main",
                "allowed_profiles": ["work_main"],
                "locked": True,
                "require_explicit_switch": True,
            }
        },
        "llm": {"openai_codex": {"transport": "sse"}},
    }
    client = ConfiguredLLMClient(saved_env={}, workspace_root=Path.cwd(), config=config)

    result = client.complete(
        provider="openai_codex",
        model="openai-codex/gpt-5.1-codex",
        messages=[{"role": "user", "content": "reply with ok"}],
        temperature=0.2,
        max_tokens=32,
    )

    assert result.text == "ok"
    assert captured["config"] == config


def test_configured_tool_backend_search_sources_skips_arxiv_dependency_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ingest import fetchers as fetchers_module
    from src.ingest import web_fetcher as web_fetcher_module

    monkeypatch.setattr(
        fetchers_module,
        "fetch_arxiv",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("feedparser is required for arXiv fetching")),
    )
    monkeypatch.setattr(
        web_fetcher_module,
        "search_semantic_scholar",
        lambda *args, **kwargs: [
            SimpleNamespace(
                uid="paper_1",
                title="Paper 1",
                snippet="A semantic scholar snippet",
                body="A semantic scholar body",
                url="https://example.com/paper-1",
                source="semantic_scholar",
                authors=["Author A"],
                year=2026,
                pdf_url="",
            )
        ],
    )

    backend = backends_module.ConfiguredToolBackend(
        root=Path.cwd(),
        saved_env={},
        config={
            "providers": {
                "search": {
                    "academic_order": ["arxiv", "semantic_scholar"],
                    "web_order": [],
                    "query_all_academic": False,
                    "query_all_web": False,
                }
            },
            "sources": {
                "arxiv": {"enabled": True, "max_results_per_query": 5},
                "semantic_scholar": {
                    "enabled": True,
                    "max_results_per_query": 5,
                    "polite_delay_sec": 0,
                    "max_retries": 1,
                    "retry_backoff_sec": 0,
                },
                "web": {"enabled": False},
            },
        },
    )

    results = backend.search_sources("dynamic research agents", 5)

    assert len(results["results"]) == 1
    assert results["results"][0]["source"] == "semantic_scholar"
    assert results["results"][0]["paper_id"] == "paper_1"
    assert results["warnings"] == ["arxiv: feedparser is required for arXiv fetching"]


def test_configured_tool_backend_search_sources_returns_warning_when_all_sources_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ingest import fetchers as fetchers_module
    from src.ingest import web_fetcher as web_fetcher_module

    monkeypatch.setattr(
        fetchers_module,
        "fetch_arxiv",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("feedparser is required for arXiv fetching")),
    )
    monkeypatch.setattr(
        web_fetcher_module,
        "search_semantic_scholar",
        lambda *args, **kwargs: [],
    )

    backend = backends_module.ConfiguredToolBackend(
        root=Path.cwd(),
        saved_env={},
        config={
            "providers": {
                "search": {
                    "academic_order": ["arxiv", "semantic_scholar"],
                    "web_order": [],
                    "query_all_academic": False,
                    "query_all_web": False,
                }
            },
            "sources": {
                "arxiv": {"enabled": True, "max_results_per_query": 5},
                "semantic_scholar": {
                    "enabled": True,
                    "max_results_per_query": 5,
                    "polite_delay_sec": 0,
                    "max_retries": 1,
                    "retry_backoff_sec": 0,
                },
                "web": {"enabled": False},
            },
        },
    )

    results = backend.search_sources("dynamic research agents", 5)

    assert results["results"] == []
    assert results["warnings"] == ["arxiv: feedparser is required for arXiv fetching"]


def test_configured_tool_backend_retrieve_documents_fetches_direct_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ingest import web_fetcher as web_fetcher_module

    monkeypatch.setattr(web_fetcher_module, "fetch_page_content", lambda url: f"full page for {url}")

    backend = backends_module.ConfiguredToolBackend(
        root=Path.cwd(),
        saved_env={},
        config={},
    )

    documents = backend.retrieve_documents(
        "dynamic research agents",
        1,
        {
            "paper_id": "paper_1",
            "title": "Paper One",
            "url": "https://example.com/paper-1",
        },
    )

    assert documents[0]["paper_id"] == "paper_1"
    assert documents[0]["fetch_method"] == "html"
    assert documents[0]["content"] == "full page for https://example.com/paper-1"


def test_openai_codex_token_persist_uses_profile_vault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_path = Path.cwd() / ".tmp_openai_codex_profiles.json"
    auth_path.unlink(missing_ok=True)
    monkeypatch.setattr(openai_codex_module, "OPENAI_CODEX_AUTH_PATH", auth_path)

    try:
        stored = openai_codex_module._persist_token_response(  # noqa: SLF001
            {
                "access_token": "not-a-jwt",
                "refresh_token": "refresh-123",
                "expires_in": 300,
                "account_id": "acct_123",
            },
            profile_id="work_main",
        )
        vault = openai_codex_module.read_openai_codex_auth_file()
        profiles = vault["providers"]["openai_codex"]["profiles"]

        assert stored["profile_id"] == "work_main"
        assert profiles["work_main"]["tokens"]["access_token"] == "not-a-jwt"
        assert profiles["work_main"]["tokens"]["refresh_token"] == "refresh-123"
        assert profiles["work_main"]["tokens"]["account_id"] == "acct_123"
    finally:
        auth_path.unlink(missing_ok=True)
        auth_path.with_name(f"{auth_path.name}.lock").unlink(missing_ok=True)


def test_openai_codex_binding_rejects_unlisted_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_path = Path.cwd() / ".tmp_openai_codex_profiles_blocked.json"
    auth_path.unlink(missing_ok=True)
    monkeypatch.setattr(openai_codex_module, "OPENAI_CODEX_AUTH_PATH", auth_path)

    try:
        with pytest.raises(RuntimeError, match="not allowed"):
            openai_codex_module.ensure_openai_codex_auth(
                config={
                    "auth": {
                        "openai_codex": {
                            "default_profile": "work_main",
                            "allowed_profiles": ["work_main"],
                            "locked": False,
                            "require_explicit_switch": True,
                        }
                    }
                },
                profile_id="personal_main",
            )
    finally:
        auth_path.unlink(missing_ok=True)
        auth_path.with_name(f"{auth_path.name}.lock").unlink(missing_ok=True)


def test_openai_codex_model_catalog_merges_known_and_verified_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = Path.cwd() / ".tmp_openai_codex_models_test.json"
    cache_path.unlink(missing_ok=True)
    monkeypatch.setattr(openai_codex_module, "OPENAI_CODEX_MODELS_CACHE_PATH", cache_path)

    try:
        openai_codex_module.remember_openai_codex_model("custom-codex-preview", label="Custom Preview")
        catalog = openai_codex_module.openai_codex_model_catalog()
        options = catalog["modelsByVendor"]["openai"]
        values = {item["value"] for item in options}

        assert "openai-codex/gpt-5.4" in values
        assert "openai-codex/gpt-5.1-codex" in values
        assert "openai-codex/custom-codex-preview" in values
    finally:
        cache_path.unlink(missing_ok=True)


def test_start_openai_codex_login_uses_openclaw_oauth_authorize_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(openai_codex_module, "_ensure_callback_server", lambda: None)
    monkeypatch.setattr(openai_codex_module, "_code_verifier", lambda: "verifier-123")
    monkeypatch.setattr(openai_codex_module.secrets, "token_urlsafe", lambda size=32: "state-123")
    monkeypatch.setattr(
        openai_codex_module,
        "openai_codex_login_status",
        lambda **kwargs: {"login_in_progress": True},
    )
    with openai_codex_module._PENDING_LOGIN_LOCK:
        openai_codex_module._PENDING_LOGIN.clear()

    try:
        payload = openai_codex_module.start_openai_codex_login()
        parsed = urllib.parse.urlparse(payload["authorize_url"])
        query = urllib.parse.parse_qs(parsed.query)

        assert parsed.scheme == "https"
        assert parsed.netloc == "auth.openai.com"
        assert parsed.path == "/oauth/authorize"
        assert query["client_id"] == [openai_codex_module.CLIENT_ID]
        assert query["redirect_uri"] == [openai_codex_module.REDIRECT_URI]
        assert query["scope"] == [openai_codex_module.SCOPE]
        assert query["response_type"] == ["code"]
        assert query["code_challenge_method"] == ["S256"]
        assert query["state"] == ["state-123"]
        assert query["id_token_add_organizations"] == ["true"]
        assert query["codex_cli_simplified_flow"] == ["true"]
        assert query["originator"] == [openai_codex_module.OPENAI_CODEX_OAUTH_ORIGINATOR]
        assert payload["status"]["login_in_progress"] is True
        assert openai_codex_module._PENDING_LOGIN["profile_id"] == openai_codex_module.DEFAULT_OPENAI_CODEX_PROFILE
    finally:
        with openai_codex_module._PENDING_LOGIN_LOCK:
            openai_codex_module._PENDING_LOGIN.clear()


def test_configured_llm_client_openai_codex_websocket_uses_top_level_response_create_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.sent_messages: list[str] = []
            self._recv_queue = [
                json.dumps({"type": "response.output_text.delta", "delta": "ok"}),
                json.dumps(
                    {
                        "type": "response.completed",
                        "response": {
                            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
                        },
                    }
                ),
            ]
            self.closed = False

        def send(self, payload: str) -> None:
            self.sent_messages.append(payload)

        def recv(self) -> str | None:
            if not self._recv_queue:
                return None
            return self._recv_queue.pop(0)

        def close(self) -> None:
            self.closed = True

    fake_connection = FakeConnection()

    monkeypatch.setattr(
        backends_module,
        "ensure_openai_codex_auth",
        lambda **kwargs: {"tokens": {"access_token": "token", "account_id": "acct_123"}},
    )
    monkeypatch.setattr(backends_module, "remember_openai_codex_model", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        backends_module.websocket,
        "create_connection",
        lambda *args, **kwargs: fake_connection,
    )

    result = ConfiguredLLMClient(
        saved_env={},
        workspace_root=Path.cwd(),
        config={"llm": {"openai_codex": {"transport": "websocket"}}},
    ).complete(
        provider="openai_codex",
        model="openai-codex/gpt-5.1-codex",
        messages=[{"role": "user", "content": "reply with ok"}],
        temperature=0.2,
        max_tokens=32,
    )

    sent_payload = json.loads(fake_connection.sent_messages[0])
    assert sent_payload["type"] == "response.create"
    assert sent_payload["model"] == "gpt-5.1-codex"
    assert sent_payload["stream"] is True
    assert str(sent_payload["instructions"]).strip()
    assert sent_payload["input"][0]["role"] == "user"
    assert "response" not in sent_payload
    assert result.text == "ok"
    assert result.usage["total_tokens"] == 2
    assert fake_connection.closed is True


def test_openai_codex_model_catalog_refreshes_from_account_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = Path.cwd() / ".tmp_openai_codex_remote_models_test.json"
    cache_path.unlink(missing_ok=True)
    monkeypatch.setattr(openai_codex_module, "OPENAI_CODEX_MODELS_CACHE_PATH", cache_path)
    monkeypatch.setattr(
        openai_codex_module,
        "ensure_openai_codex_auth",
        lambda **kwargs: {"tokens": {"access_token": "token", "account_id": "acct_123"}},
    )

    class FakeHttpResponse:
        def __enter__(self) -> "FakeHttpResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "models": [
                        {
                            "slug": "gpt-5.4",
                            "display_name": "gpt-5.4",
                            "priority": 0,
                            "visibility": "list",
                            "supported_in_api": True,
                            "base_instructions": "Base instructions 5.4",
                        },
                        {
                            "slug": "gpt-5.3-codex",
                            "display_name": "gpt-5.3-codex",
                            "priority": 5,
                            "visibility": "list",
                            "supported_in_api": True,
                            "base_instructions": "Base instructions 5.3",
                        },
                        {
                            "slug": "gpt-5.1",
                            "display_name": "gpt-5.1",
                            "priority": 40,
                            "visibility": "hide",
                            "supported_in_api": True,
                            "base_instructions": "Base instructions 5.1",
                        },
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout=0):
        assert request.full_url.startswith(f"{openai_codex_module.OPENAI_CODEX_MODELS_URL}?")
        assert "client_version=1.0.0" in request.full_url
        headers = {key.lower(): value for key, value in request.header_items()}
        assert headers["authorization"] == "Bearer token"
        assert headers["chatgpt-account-id"] == "acct_123"
        return FakeHttpResponse()

    monkeypatch.setattr(openai_codex_module.urllib.request, "urlopen", fake_urlopen)

    try:
        catalog = openai_codex_module.openai_codex_model_catalog(
            config={"llm": {"openai_codex": {"model_discovery": "account_plus_cached"}}}
        )
        values = {item["value"] for item in catalog["modelsByVendor"]["openai"]}
        metadata = openai_codex_module.openai_codex_model_metadata("gpt-5.3-codex")

        assert "openai-codex/gpt-5.4" in values
        assert "openai-codex/gpt-5.3-codex" in values
        assert "openai-codex/gpt-5.1" in values
        assert metadata["base_instructions"] == "Base instructions 5.3"
    finally:
        cache_path.unlink(missing_ok=True)
        cache_path.with_name(f"{cache_path.name}.lock").unlink(missing_ok=True)


def test_complete_openai_codex_login_accepts_callback_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        openai_codex_module,
        "_complete_pending_login",
        lambda *, code="", state="", error="": captured.update(
            {"code": code, "state": state, "error": error}
        ),
    )
    monkeypatch.setattr(
        openai_codex_module,
        "openai_codex_login_status",
        lambda **kwargs: {"logged_in": True, "login_in_progress": False},
    )

    result = openai_codex_module.complete_openai_codex_login(
        "http://localhost:1455/auth/callback?code=code-123&state=state-123"
    )

    assert captured == {"code": "code-123", "state": "state-123", "error": ""}
    assert result["logged_in"] is True


def test_complete_openai_codex_login_accepts_bare_code_with_pending_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        openai_codex_module,
        "_complete_pending_login",
        lambda *, code="", state="", error="": captured.update(
            {"code": code, "state": state, "error": error}
        ),
    )
    monkeypatch.setattr(
        openai_codex_module,
        "openai_codex_login_status",
        lambda **kwargs: {"logged_in": True, "login_in_progress": False},
    )
    with openai_codex_module._PENDING_LOGIN_LOCK:
        openai_codex_module._PENDING_LOGIN.clear()
        openai_codex_module._PENDING_LOGIN.update(
            {
                "profile_id": openai_codex_module.DEFAULT_OPENAI_CODEX_PROFILE,
                "state": "pending-state",
                "code_verifier": "verifier",
                "authorize_url": "https://auth.openai.com/oauth/authorize?state=pending-state",
                "expires_at": openai_codex_module._now_epoch_seconds() + 60,
                "last_error": "",
            }
        )

    try:
        result = openai_codex_module.complete_openai_codex_login("code-456")
    finally:
        with openai_codex_module._PENDING_LOGIN_LOCK:
            openai_codex_module._PENDING_LOGIN.clear()

    assert captured == {"code": "code-456", "state": "pending-state", "error": ""}
    assert result["logged_in"] is True
