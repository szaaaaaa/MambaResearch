import asyncio

import pytest

from src.dynamic_os.contracts.policy import BudgetPolicy
from src.dynamic_os.policy.engine import BudgetExceededError, PolicyEngine
from src.dynamic_os.tools.gateway.mcp import McpGateway
from src.dynamic_os.tools.registry import ToolRegistry

MESSAGES = [{"role": "user", "content": "A question"}]


def test_reservations_account_for_concurrent_calls_and_unknown_usage():
    policy = PolicyEngine(budget_policy=BudgetPolicy(max_tokens=10000))
    with policy.llm_request(MESSAGES, 20000) as first:
        assert 0 < first.max_tokens < 10000
        with pytest.raises(BudgetExceededError):
            with policy.llm_request(MESSAGES, 1):
                pytest.fail("a concurrent call consumed the reserved budget")
        first.usage = {"total_tokens": 200}
    assert policy.snapshot()["tokens_used"] == 200
    with pytest.raises(RuntimeError, match="transport failed"):
        with policy.llm_request(MESSAGES, 20000) as failed:
            failed.usage = ["invalid provider usage"]
            raise RuntimeError("transport failed")
    assert policy.snapshot()["tokens_used"] == 10000
    assert policy.snapshot()["tokens_reserved"] == 0


def test_gateway_caps_output_and_blocks_oversized_input_before_invocation():
    calls = []
    async def invoke(tool, payload):
        calls.append(payload)
        assert payload["max_tokens"] < 10000
        return {"content": "answer", "usage": {"total_tokens": 100}}
    policy = PolicyEngine(budget_policy=BudgetPolicy(max_tokens=10000))
    registry = ToolRegistry.from_servers([{"server_id": "llm", "tools": [{"name": "chat", "capability": "llm_chat"}]}])
    gateway = McpGateway(registry=registry, policy=policy, invoker=invoke)
    result = asyncio.run(gateway.invoke_tool("mcp.llm.chat", {"messages": MESSAGES, "max_tokens": 20000}))
    assert result == "answer"
    with pytest.raises(BudgetExceededError):
        asyncio.run(gateway.invoke_tool("mcp.llm.chat", {"messages": [{"role": "user", "content": "x" * 100000}]}))
    assert len(calls) == 1
    assert policy.snapshot()["tokens_used"] == 100


def test_non_llm_tool_usage_still_counts_toward_budget():
    policy = PolicyEngine(budget_policy=BudgetPolicy(max_tokens=10000))
    registry = ToolRegistry.from_servers([{"server_id": "retrieval", "tools": [{"name": "index", "capability": "index"}]}])
    def invoke(tool, payload):
        return {"content": {"indexed": 1}, "usage": {"total_tokens": 700}}
    gateway = McpGateway(registry=registry, policy=policy, invoker=invoke)
    assert asyncio.run(gateway.invoke_tool("mcp.retrieval.index", {})) == {"indexed": 1}
    assert policy.snapshot()["tokens_used"] == 700
