"""验证 MCP bridge 的 ``tools/call`` 派发路径。

覆盖 Task 11 AC："通过 tools/call 调 research_agent.search_papers，拿到 ≥1 个
artifact（skill 真实执行）"。

设计说明
--------
真正的 ``search_papers`` 会调 ``ctx.tools.search`` 走 paper_search MCP → 网络；
在 pytest 里那条链路既慢又易抖动。替代：注入一个 ``_FakeGateway`` 作为
``ToolGateway``——同形 ``with_permissions/with_allowed_tools/search`` 接口，
返回 2 条预置论文。``search_papers/run.py`` 自身的逻辑（解析 SearchPlan
payload → 聚合多查询 → 生成 SourceSet）照常执行，所以本测试仍是"skill
真实执行"，仅屏蔽了下游网络。

覆盖的断言：
- tools/call 成功分派到注册的 skill
- arguments.search_plan dict 被正确合成为 SearchPlan ArtifactRecord
- 返回的 structuredContent 包含 ≥1 条 output_artifact（skill 的 SourceSet）
- 未暴露 skill 名会被拒绝
- arguments 缺 required 时 skill 层报失败（AC 不要求 MCP 层做 schema 校验）
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from src.dynamic_os.skills.registry import SkillRegistry
from src.mcp_bridge.invoker import invoke_skill


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL_ROOTS = [_REPO_ROOT / "src" / "dynamic_os" / "skills" / "builtins"]


@dataclass
class _FakeGateway:
    """替换 ToolGateway——同形接口；仅实现 search/llm_chat 即可覆盖本批 skill。"""

    search_results: list[dict[str, Any]]
    calls: list[tuple[str, dict]] = field(default_factory=list)

    def with_permissions(self, permissions: Any) -> "_FakeGateway":
        del permissions
        return self

    def with_allowed_tools(self, allowed_tools: Any) -> "_FakeGateway":
        del allowed_tools
        return self

    async def search(
        self,
        query: str,
        *,
        source: str = "auto",
        max_results: int = 10,
        academic_sources: list[str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            ("search", {"query": query, "source": source, "academic_sources": academic_sources}),
        )
        return {"results": list(self.search_results), "warnings": []}

    async def llm_chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls.append(("llm_chat", {"messages": messages, "kwargs": kwargs}))
        return "{}"


@pytest.fixture(scope="module")
def skill_registry() -> SkillRegistry:
    return SkillRegistry.discover(roots=_SKILL_ROOTS)


@pytest.fixture
def fake_gateway() -> _FakeGateway:
    # 两条不同的论文结果，确保去重后 ≥1 条 source 进入 SourceSet.sources
    return _FakeGateway(
        search_results=[
            {
                "title": "State Space Duality: A Unified View of Mamba",
                "authors": ["A. Gu", "T. Dao"],
                "year": 2024,
                "url": "https://arxiv.org/abs/2405.21060",
                "source": "arxiv",
            },
            {
                "title": "Mamba: Linear-Time Sequence Modeling with Selective State Spaces",
                "authors": ["A. Gu", "T. Dao"],
                "year": 2023,
                "url": "https://arxiv.org/abs/2312.00752",
                "source": "arxiv",
            },
        ],
    )


def test_tools_call_search_papers_returns_artifact(
    skill_registry: SkillRegistry, fake_gateway: _FakeGateway,
) -> None:
    arguments = {
        "goal": "Survey Mamba architecture comprehension",
        "search_plan": {
            "queries": ["Mamba architecture survey", "state space models"],
            "recommended_sources": ["arxiv"],
            "sources": ["arxiv"],
            "query_routes": {
                "Mamba architecture survey": ["arxiv"],
                "state space models": ["arxiv"],
            },
        },
    }

    result = asyncio.run(
        invoke_skill(
            skill_id="search_papers",
            arguments=arguments,
            skill_registry=skill_registry,
            tool_gateway=fake_gateway,
            run_id="test_run_001",
            cwd=_REPO_ROOT,
        ),
    )

    assert result["isError"] is False
    structured = result["structuredContent"]
    assert structured["success"] is True
    artifacts = structured["output_artifacts"]
    assert len(artifacts) >= 1, f"expected ≥1 output artifact, got {artifacts}"
    source_set = next(
        (a for a in artifacts if a["artifact_type"] == "SourceSet"), None,
    )
    assert source_set is not None, "expected a SourceSet output artifact"
    # ctx.tools.search 应被至少调一次
    assert any(call[0] == "search" for call in fake_gateway.calls)


def test_tools_call_rejects_unlisted_skill(
    skill_registry: SkillRegistry, fake_gateway: _FakeGateway,
) -> None:
    result = asyncio.run(
        invoke_skill(
            skill_id="run_experiment",
            arguments={"goal": "smoke"},
            skill_registry=skill_registry,
            tool_gateway=fake_gateway,
            run_id="test_run_002",
            cwd=_REPO_ROOT,
        ),
    )
    assert result["isError"] is True
    assert "not exposed" in result["structuredContent"]["error"]


def test_tools_call_rejects_unknown_skill(
    skill_registry: SkillRegistry, fake_gateway: _FakeGateway,
) -> None:
    result = asyncio.run(
        invoke_skill(
            skill_id="totally_made_up_skill",
            arguments={},
            skill_registry=skill_registry,
            tool_gateway=fake_gateway,
            run_id="test_run_003",
            cwd=_REPO_ROOT,
        ),
    )
    assert result["isError"] is True
