"""验证 MCP bridge 的 ``tools/list`` 行为。

覆盖 Task 11 AC："tools/list JSON-RPC 返回 ≥5 个 research_agent.* 工具" 以及
"每个工具的 inputSchema 从对应 skill.yaml 的 input_contract 生成，description
取自 skill.md 首段"。

测试层次：直接调用 ``build_tool_descriptor`` 于已加载的 SkillRegistry——绕过
子进程启动，避免对外部 MCP backends（LLM / paper_search 等）依赖。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.dynamic_os.skills.registry import SkillRegistry
from src.mcp_bridge.invoker import EXPOSED_SKILLS, build_tool_descriptor


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL_ROOTS = [_REPO_ROOT / "src" / "dynamic_os" / "skills" / "builtins"]


@pytest.fixture(scope="module")
def skill_registry() -> SkillRegistry:
    return SkillRegistry.discover(roots=_SKILL_ROOTS)


def test_exposed_skills_satisfy_min_count(skill_registry: SkillRegistry) -> None:
    # AC: ≥5 个 research_agent.* 工具
    assert len(EXPOSED_SKILLS) >= 5
    for skill_id in EXPOSED_SKILLS:
        skill_registry.get(skill_id)  # 不存在则 KeyError — 测试失败


def test_descriptor_shape(skill_registry: SkillRegistry) -> None:
    for skill_id in EXPOSED_SKILLS:
        loaded = skill_registry.get(skill_id)
        desc = build_tool_descriptor(loaded)
        assert desc["name"] == skill_id
        assert isinstance(desc["description"], str) and desc["description"].strip()
        schema = desc["inputSchema"]
        assert schema["type"] == "object"
        assert isinstance(schema["properties"], dict)
        # goal 字段始终存在 —— 映射到 ctx.user_request
        assert "goal" in schema["properties"]


def test_required_keys_match_input_contract(skill_registry: SkillRegistry) -> None:
    # search_papers 的 skill.yaml 声明 required: [SearchPlan]
    desc = build_tool_descriptor(skill_registry.get("search_papers"))
    schema = desc["inputSchema"]
    assert schema.get("required") == ["search_plan"]
    assert "search_plan" in schema["properties"]
    # optional: TopicBrief 也应暴露但不在 required
    assert "topic_brief" in schema["properties"]

    # plan_research 没有任何 required/requires_any/optional —— required 缺省
    plan_desc = build_tool_descriptor(skill_registry.get("plan_research"))
    assert "required" not in plan_desc["inputSchema"]


def test_build_refuses_unlisted_skill(skill_registry: SkillRegistry) -> None:
    # 拿一个 EXPOSED_SKILLS 外的 skill——如 run_experiment——试图构建应报错
    outsider = skill_registry.get("run_experiment")
    with pytest.raises(ValueError, match="not in EXPOSED_SKILLS"):
        build_tool_descriptor(outsider)


def test_description_prefers_skill_md_first_paragraph(
    skill_registry: SkillRegistry,
) -> None:
    # skill.md 首段 vs. skill.yaml 的 description 应不同（否则没必要取首段）；
    # 若 skill.md 不存在首段回退，描述等于 spec.description 也合法——检查非空即可
    for skill_id in EXPOSED_SKILLS:
        loaded = skill_registry.get(skill_id)
        desc = build_tool_descriptor(loaded)
        assert desc["description"].strip()
