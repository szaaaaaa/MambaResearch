from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.dynamic_os.contracts.policy import BudgetPolicy, PermissionPolicy
from src.dynamic_os.contracts.skill_spec import SkillPermissions
from src.dynamic_os.policy.engine import BudgetExceededError, PolicyEngine, PolicyViolationError
from src.dynamic_os.tools import backends as backends_module
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
                "server_id": "paper_search",
                "tools": [
                    {"name": "search_papers", "capability": "search"},
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

    result = asyncio.run(gateway.search("retrieval planning", source="academic", max_results=5))

    assert result == {
        "results": [{"paper_id": "arxiv:2401.00001", "title": "Test Paper", "query": "retrieval planning"}],
        "warnings": [],
    }
    assert calls == [
        ("mcp.paper_search.search_papers", {"query": "retrieval planning", "source": "academic", "max_results": 5}),
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



def test_configured_tool_backend_search_sources_web_returns_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ingest import web_fetcher as web_fetcher_module

    monkeypatch.setattr(
        web_fetcher_module,
        "search_duckduckgo",
        lambda *args, **kwargs: [
            SimpleNamespace(
                uid="web_1",
                title="Web Result 1",
                snippet="A web snippet",
                body="A web body",
                url="https://example.com/web-1",
                source="duckduckgo",
            )
        ],
    )

    backend = backends_module.ConfiguredToolBackend(
        root=Path.cwd(),
        saved_env={},
        config={
            "providers": {
                "search": {
                    "web_order": ["google_cse", "bing"],
                    "query_all_web": False,
                }
            },
            "sources": {
                "web": {"enabled": True},
                "google_cse": {"enabled": False},
                "bing": {"enabled": False},
            },
        },
    )

    results = backend.search_sources("test query", 5)

    assert len(results["results"]) == 1
    assert results["results"][0]["source"] == "duckduckgo"
    assert results["results"][0]["paper_id"] == "web_1"


def test_configured_tool_backend_search_sources_skips_academic_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = backends_module.ConfiguredToolBackend(
        root=Path.cwd(),
        saved_env={},
        config={
            "providers": {
                "search": {
                    "web_order": [],
                    "query_all_web": False,
                }
            },
            "sources": {
                "web": {"enabled": False},
            },
        },
    )

    results = backend.search_sources("test query", 5, source="academic")

    assert results["results"] == []
    assert results["warnings"] == []


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


