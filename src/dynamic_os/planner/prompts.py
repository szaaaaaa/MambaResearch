"""规划器提示词构建 — 组装发送给 LLM 的系统提示和用户消息。

本模块负责将系统运行时状态（角色注册表、技能清单、artifact 列表、观测记录、
预算快照等）格式化为 LLM 可理解的文本，拼装成完整的 planner system prompt。

主要函数：
    build_planner_messages        — 构建首次规划请求的 messages 列表
    build_planner_repair_messages — 构建修复请求的 messages（当 LLM 首次输出校验失败时使用）
    planner_output_contract       — 返回 RoutePlan JSON 输出契约的文本描述

辅助函数（summarize_*）负责将各类数据结构转为紧凑的文本摘要嵌入 prompt。
"""

from __future__ import annotations

import json
from typing import Any

from src.dynamic_os.roles.registry import RoleRegistry


# 规划器系统提示词模板
# 包含占位符（{role_registry_summary} 等），在 build_planner_messages 中被实际值填充
# 该提示词告诉 LLM 它作为研究操作系统规划器的角色、可用资源和输出规范
PLANNER_SYSTEM_PROMPT = """You are the planner for a research operating system with six execution roles plus a special hitl (human-in-the-loop) node type.

Your job: given a user request and current execution state, produce a small
local execution DAG, typically 2-4 nodes. You do NOT plan the full run - only the next
meaningful segment.

## Available Roles
{role_registry_summary}

## Available Skills per Role
{skill_allowlist_summary}

## Skill Contracts
{skill_contract_summary}

## Prior Research Context (from previous runs)
{prior_research_context}

## Current State
- Artifacts produced so far: {artifact_summary}
- Exact artifact refs available now: {artifact_refs}
- Deterministic future artifact ref templates: {artifact_ref_templates}
- Latest observations: {observation_summary}
- Budget usage: {budget_snapshot}
- Planning iteration: {iteration}

## Exact Output Contract
{planner_output_contract}

## Rules
1. You have full authority to choose which roles to use. Select the smallest set of roles needed for the next step based on the user request, current artifacts, and observations.
2. Each node must specify allowed_skills from that role's allowlist. Order matters: the first skill is the preferred choice, later ones are fallbacks.
2a. allowed_skills must use exact skill ids only. Never invent names like conversation, brainstorming, summarize, or no_skill.
3. Every allowed_skill in a node must be executable with that node's input artifact types.
3a. Every node.inputs entry must be a full exact reference in the form artifact:<Type>:<artifact_id>.
3b. Existing artifact inputs must match the current exact refs list.
3c. Future artifact inputs must use an upstream node's deterministic future ref, and edges must make that producer upstream.
4. expected_outputs must contain artifact type names only, and they must be producible by the node's allowed_skills. Never use artifact ids, node ids, topic-specific aliases, or free-form names.
5. Write node.goal, success_criteria, and planner_notes in Simplified Chinese.
6. Set terminate=true when the user goal is fully satisfied.
7. Output valid JSON matching the RoutePlan schema.
8. Keep node.goal, each success_criteria item, and each planner_notes item short and concrete. Avoid long paragraphs or repeated text.
9. Keep the whole JSON compact, usually under 1500 characters unless the schema truly requires more.
10. HITL (human-in-the-loop) nodes: use role="hitl", allowed_skills=["hitl"], expected_outputs=["UserGuidance"].
    Set hitl_question to the specific question you want the human to answer.
    Use hitl nodes when: research direction is unclear and needs human validation, multiple equally valid paths exist,
    or a critical decision requires human judgment before proceeding.
    A UserGuidance artifact from a hitl node can be referenced as input by subsequent nodes.
"""


def planner_output_contract() -> str:
    """返回 RoutePlan 的 JSON 输出契约描述文本。

    该文本会嵌入 system prompt，告知 LLM 输出必须严格遵守的 JSON 结构规范，
    包括顶层键、节点键、边键的名称和类型约束，以及一个骨架示例。
    """
    return (
        "Top-level keys only: "
        "[run_id, planning_iteration, horizon, nodes, edges, planner_notes, terminate]. "
        "Each node keys only: "
        "[node_id, role, goal, inputs, allowed_skills, success_criteria, failure_policy, expected_outputs, hitl_question]. "
        "Forbidden legacy node keys: [agent_id, agent_name, skill, planner_notes]. "
        "node_id must match ^node_[a-z0-9_]+$. "
        "inputs must be a list of artifact refs, never an object. "
        "success_criteria must be a list of strings, never a single string. "
        "planner_notes exists only at the top level and must be a list of strings. "
        "failure_policy must be one of [replan, skip, abort]. "
        "Each edge keys only: [source, target, condition]. "
        "source and target must be valid node_id values. condition must be one of [on_success, on_failure, always] (default: on_success). "
        "NEVER use source_id, target_id, or artifact_id in edges — these are forbidden. "
        "HITL node: role=hitl, allowed_skills=[hitl], expected_outputs=[UserGuidance], hitl_question=<question for human>. "
        "Example skeleton: "
        '{"run_id":"<same run_id>","planning_iteration":0,"horizon":2,"nodes":[{"node_id":"node_plan_1","role":"conductor","goal":"...","inputs":[],"allowed_skills":["plan_research"],"success_criteria":["..."],"failure_policy":"replan","expected_outputs":["TopicBrief","SearchPlan"],"hitl_question":""},{"node_id":"node_search_1","role":"researcher","goal":"...","inputs":["artifact:SearchPlan:node_plan_1"],"allowed_skills":["search_papers"],"success_criteria":["..."],"failure_policy":"replan","expected_outputs":["SourceSet"],"hitl_question":""}],"edges":[{"source":"node_plan_1","target":"node_search_1","condition":"on_success"}],"planner_notes":["..."],"terminate":false}'
    )


def summarize_roles(role_registry: RoleRegistry) -> str:
    """将角色注册表格式化为 Markdown 列表，嵌入 prompt 供 LLM 了解可用角色。"""
    return "\n".join(
        f"- {role.id.value}: {role.description}"
        for role in role_registry.list()
    )


def summarize_skill_allowlists(
    role_registry: RoleRegistry,
    available_skills_by_role: dict[str, list[str]],
) -> str:
    """将每个角色允许使用的技能列表格式化为文本摘要。"""
    lines: list[str] = []
    for role in role_registry.list():
        skills = available_skills_by_role.get(role.id.value, [])
        rendered = ", ".join(skills) if skills else "(none)"
        lines.append(f"- {role.id.value}: {rendered}")
    return "\n".join(lines)


def summarize_skill_contracts(skill_contract_summary: dict[str, dict[str, dict[str, list[str]]]]) -> str:
    """将技能输入/输出契约格式化为文本，帮助 LLM 理解每个技能的数据依赖关系。"""
    lines: list[str] = []
    for role_id, skills in skill_contract_summary.items():
        for skill_id, contract in skills.items():
            required = ", ".join(contract.get("required", [])) or "(none)"
            requires_any = ", ".join(contract.get("requires_any", [])) or "(none)"
            outputs = ", ".join(contract.get("outputs", [])) or "(none)"
            lines.append(
                f"- {role_id}.{skill_id}: required=[{required}], requires_any=[{requires_any}], outputs=[{outputs}]"
            )
    return "\n".join(lines) if lines else "(none)"


def summarize_artifacts(artifacts: list[dict[str, str]]) -> str:
    """将 artifact 摘要列表序列化为 JSON 字符串（未分层，简单版本）。"""
    if not artifacts:
        return "[]"
    return json.dumps(artifacts, ensure_ascii=False)


def summarize_artifacts_tiered(
    artifacts: list[dict[str, str]],
    planning_iteration: int,
    hot_window: int = 3,
) -> str:
    """将 artifact 列表分层摘要：热区保留完整，冷区压缩为类型计数。"""
    if not artifacts:
        return "[]"
    if len(artifacts) <= hot_window:
        return json.dumps(artifacts, ensure_ascii=False)

    # 冷区：按类型计数
    cold = artifacts[:-hot_window]
    type_counts: dict[str, int] = {}
    for a in cold:
        t = a.get("artifact_type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    cold_summary = "Earlier artifacts: " + ", ".join(
        f"{count}× {atype}" for atype, count in type_counts.items()
    )

    # 热区：完整保留
    hot = artifacts[-hot_window:]
    return cold_summary + "\nRecent artifacts: " + json.dumps(hot, ensure_ascii=False)


def summarize_artifact_refs(artifact_refs: list[str]) -> str:
    """将已存在的精确 artifact 引用列表序列化为 JSON。"""
    if not artifact_refs:
        return "[]"
    return json.dumps(artifact_refs, ensure_ascii=False)


def summarize_artifact_ref_templates(artifact_ref_templates: list[dict[str, str]]) -> str:
    """将确定性 artifact 引用模板序列化为 JSON，帮助 LLM 正确构造 future refs。"""
    if not artifact_ref_templates:
        return "[]"
    return json.dumps(artifact_ref_templates, ensure_ascii=False)


def summarize_observations(observations: list[dict[str, Any]]) -> str:
    """将最近的节点观测记录序列化为 JSON。"""
    if not observations:
        return "[]"
    return json.dumps(observations, ensure_ascii=False)


def build_planner_messages(
    *,
    user_request: str,
    role_registry: RoleRegistry,
    available_skills_by_role: dict[str, list[str]],
    skill_contract_summary: dict[str, dict[str, dict[str, list[str]]]],
    artifact_summary: list[dict[str, str]],
    artifact_refs: list[str],
    artifact_ref_templates: list[dict[str, str]],
    observation_summary: list[dict[str, Any]],
    budget_snapshot: dict[str, Any],
    planning_iteration: int,
    prior_research_context: str = "",
) -> list[dict[str, str]]:
    """构建首次规划请求的 LLM messages 列表。

    将系统运行时的所有上下文信息填充进 PLANNER_SYSTEM_PROMPT 模板，
    生成 [system, user] 两条消息，供 LLM 生成 RoutePlan JSON。

    参数
    ----------
    user_request : str
        用户的原始研究请求文本。
    role_registry : RoleRegistry
        角色注册表实例。
    available_skills_by_role : dict
        各角色当前可用技能列表。
    skill_contract_summary : dict
        各技能的输入/输出契约摘要。
    artifact_summary : list
        已产出 artifact 的摘要。
    artifact_refs : list
        已存在的精确 artifact 引用。
    artifact_ref_templates : list
        确定性的未来 artifact 引用模板。
    observation_summary : list
        最近的节点观测记录。
    budget_snapshot : dict
        当前预算使用情况。
    planning_iteration : int
        当前规划迭代次数。
    prior_research_context : str
        来自历史运行的先验研究上下文。

    返回
    -------
    list[dict[str, str]]
        包含 system 和 user 两条消息的列表。
    """
    system_prompt = PLANNER_SYSTEM_PROMPT.format(
        role_registry_summary=summarize_roles(role_registry),
        skill_allowlist_summary=summarize_skill_allowlists(role_registry, available_skills_by_role),
        skill_contract_summary=summarize_skill_contracts(skill_contract_summary),
        artifact_summary=summarize_artifacts_tiered(artifact_summary, planning_iteration),
        artifact_refs=summarize_artifact_refs(artifact_refs),
        artifact_ref_templates=summarize_artifact_ref_templates(artifact_ref_templates),
        observation_summary=summarize_observations(observation_summary),
        budget_snapshot=json.dumps(budget_snapshot, ensure_ascii=False),
        iteration=planning_iteration,
        planner_output_contract=planner_output_contract(),
        prior_research_context=prior_research_context or "(none)",
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_request},
    ]


def build_planner_repair_messages(
    *,
    user_request: str,
    role_registry: RoleRegistry,
    available_skills_by_role: dict[str, list[str]],
    skill_contract_summary: dict[str, dict[str, dict[str, list[str]]]],
    artifact_summary: list[dict[str, str]],
    artifact_refs: list[str],
    artifact_ref_templates: list[dict[str, str]],
    observation_summary: list[dict[str, Any]],
    budget_snapshot: dict[str, Any],
    planning_iteration: int,
    validation_error: str,
    raw_output: str,
    prior_research_context: str = "",
) -> list[dict[str, str]]:
    """构建修复请求的 LLM messages 列表。

    当 LLM 首次输出的 RoutePlan JSON 校验失败时，使用此函数构建修复提示，
    将校验错误信息和原始无效输出一并发送给 LLM，要求它修正 JSON。

    参数
    ----------
    validation_error : str
        首次输出的校验错误详情。
    raw_output : str
        LLM 首次输出的原始文本。
    其余参数与 build_planner_messages 相同。

    返回
    -------
    list[dict[str, str]]
        包含 system 和 user 两条消息的修复请求。
    """
    system_prompt = (
        "You are a JSON repair assistant for RoutePlan. "
        "Your only job is to rewrite the previous invalid planner output into valid JSON that matches the exact RoutePlan contract. "
        "Do not add markdown fences. Do not explain. Return corrected JSON only.\n\n"
        f"## Available Roles\n{summarize_roles(role_registry)}\n\n"
        f"## Available Skills per Role\n{summarize_skill_allowlists(role_registry, available_skills_by_role)}\n\n"
        f"## Skill Contracts\n{summarize_skill_contracts(skill_contract_summary)}\n\n"
        f"## Current State\n"
        f"- Artifacts produced so far: {summarize_artifacts_tiered(artifact_summary, planning_iteration)}\n"
        f"- Exact artifact refs available now: {summarize_artifact_refs(artifact_refs)}\n"
        f"- Deterministic future artifact ref templates: {summarize_artifact_ref_templates(artifact_ref_templates)}\n"
        f"- Latest observations: {summarize_observations(observation_summary)}\n"
        f"- Budget usage: {json.dumps(budget_snapshot, ensure_ascii=False)}\n"
        f"- Planning iteration: {planning_iteration}\n\n"
        f"## Exact Output Contract\n{planner_output_contract()}\n"
    )
    user_prompt = (
        f"Original user request:\n{user_request}\n\n"
        f"Validation error:\n{validation_error}\n\n"
        f"Previous invalid planner output:\n{raw_output}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


