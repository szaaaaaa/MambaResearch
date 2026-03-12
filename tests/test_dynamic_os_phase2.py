from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.dynamic_os.contracts.policy import BudgetPolicy, PermissionPolicy
from src.dynamic_os.contracts.skill_spec import SkillPermissions
from src.dynamic_os.policy.engine import BudgetExceededError, PolicyEngine, PolicyViolationError
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

    with pytest.raises(BudgetExceededError, match="tool invocation budget exceeded"):
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
        return [{"tool_id": tool.tool_id, "query": payload["query"]}]

    gateway = ToolGateway(registry=registry, policy=engine, mcp_invoker=invoker)

    result = asyncio.run(gateway.search("retrieval planning", source="arxiv", max_results=5))

    assert result == [{"tool_id": "mcp.search.arxiv", "query": "retrieval planning"}]
    assert calls == [
        ("mcp.search.arxiv", {"query": "retrieval planning", "max_results": 5}),
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
