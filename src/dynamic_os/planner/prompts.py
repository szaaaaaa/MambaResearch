from __future__ import annotations

import json
from typing import Any

from src.dynamic_os.planner.routing import RoleRoutingPolicy
from src.dynamic_os.roles.registry import RoleRegistry


ROLE_ROUTER_SYSTEM_PROMPT = """You are the role router for a research operating system.

Your job: before DAG planning, decide the smallest useful set of execution roles
for the next segment.

## Available Roles
{role_registry_summary}

## Available Skills per Role
{skill_allowlist_summary}

## Current State
- Artifacts produced so far: {artifact_summary}
- Exact artifact refs available now: {artifact_refs}
- Latest observations: {observation_summary}
- Budget usage: {budget_snapshot}
- Planning iteration: {iteration}

## Hard Routing Policy From Code
{role_routing_summary}

## Rules
1. selected_roles must contain the only roles the next plan is allowed to use.
2. required_roles must be a subset of selected_roles.
3. Include every hard required role from the policy.
4. Keep the role set small, usually 1-3 roles.
5. Do not select writer, reviewer, analyst, or experimenter prematurely.
6. Write reasons in Simplified Chinese.
7. Return valid JSON only.
"""


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

## Current State
- Artifacts produced so far: {artifact_summary}
- Exact artifact refs available now: {artifact_refs}
- Deterministic future artifact ref templates: {artifact_ref_templates}
- Role routing policy now: {role_routing_summary}
- Latest observations: {observation_summary}
- Budget usage: {budget_snapshot}
- Planning iteration: {iteration}

## Exact Output Contract
{planner_output_contract}

## Rules
1. Select the smallest set of roles needed for the next step.
2. Each node must specify allowed_skills from that role's allowlist.
2a. allowed_skills must use exact skill ids only. Never invent names like conversation, brainstorming, summarize, or no_skill.
3. Every allowed_skill in a node must be executable with that node's input artifact types.
3a. Every node.inputs entry must be a full exact reference in the form artifact:<Type>:<artifact_id>.
3b. Existing artifact inputs must match the current exact refs list.
3c. Future artifact inputs must use an upstream node's deterministic future ref, and edges must make that producer upstream.
4. expected_outputs must contain artifact type names only, and they must be producible by the node's allowed_skills. Never use artifact ids, node ids, topic-specific aliases, or free-form names.
5. Write node.goal, success_criteria, and planner_notes in Simplified Chinese.
6. Set needs_review=true only when output uncertainty is high, evidence
   conflicts, or a critical deliverable is about to be produced.
7. Set terminate=true when the user goal is fully satisfied.
8. Output valid JSON matching the RoutePlan schema.
9. Include every required role from the routing policy unless terminate=true.
10. Use only roles listed in selected_roles from the routing policy unless terminate=true.
11. Prefer the preferred roles from the routing policy when they fit the next step.
12. Only activate experimenter, analyst, writer, or reviewer when node.inputs directly include the required artifact types from the routing policy.
13. Keep node.goal, each success_criteria item, and each planner_notes item short and concrete. Avoid long paragraphs or repeated text.
14. Keep the whole JSON compact, usually under 1500 characters unless the schema truly requires more.
15. HITL (human-in-the-loop) nodes: use role="hitl", allowed_skills=["hitl"], expected_outputs=["UserGuidance"].
    Set hitl_question to the specific question you want the human to answer.
    Use hitl nodes when: research direction is unclear and needs human validation, multiple equally valid paths exist,
    or a critical decision requires human judgment before proceeding.
    A UserGuidance artifact from a hitl node can be referenced as input by subsequent nodes.
"""


def planner_output_contract() -> str:
    return (
        "Top-level keys only: "
        "[run_id, planning_iteration, horizon, nodes, edges, planner_notes, terminate]. "
        "Each node keys only: "
        "[node_id, role, goal, inputs, allowed_skills, success_criteria, failure_policy, expected_outputs, needs_review, hitl_question]. "
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
        '{"run_id":"<same run_id>","planning_iteration":0,"horizon":2,"nodes":[{"node_id":"node_plan_1","role":"conductor","goal":"...","inputs":[],"allowed_skills":["plan_research"],"success_criteria":["..."],"failure_policy":"replan","expected_outputs":["TopicBrief","SearchPlan"],"needs_review":false,"hitl_question":""},{"node_id":"node_search_1","role":"researcher","goal":"...","inputs":["artifact:SearchPlan:node_plan_1"],"allowed_skills":["search_papers"],"success_criteria":["..."],"failure_policy":"replan","expected_outputs":["SourceSet"],"needs_review":false,"hitl_question":""}],"edges":[{"source":"node_plan_1","target":"node_search_1","condition":"on_success"}],"planner_notes":["..."],"terminate":false}'
    )


def summarize_roles(role_registry: RoleRegistry) -> str:
    return "\n".join(
        f"- {role.id.value}: {role.description}"
        for role in role_registry.list()
    )


def summarize_skill_allowlists(
    role_registry: RoleRegistry,
    available_skills_by_role: dict[str, list[str]],
) -> str:
    lines: list[str] = []
    for role in role_registry.list():
        skills = available_skills_by_role.get(role.id.value, [])
        rendered = ", ".join(skills) if skills else "(none)"
        lines.append(f"- {role.id.value}: {rendered}")
    return "\n".join(lines)


def summarize_skill_contracts(skill_contract_summary: dict[str, dict[str, dict[str, list[str]]]]) -> str:
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
    if not artifacts:
        return "[]"
    return json.dumps(artifacts, ensure_ascii=False)


def summarize_artifact_refs(artifact_refs: list[str]) -> str:
    if not artifact_refs:
        return "[]"
    return json.dumps(artifact_refs, ensure_ascii=False)


def summarize_artifact_ref_templates(artifact_ref_templates: list[dict[str, str]]) -> str:
    if not artifact_ref_templates:
        return "[]"
    return json.dumps(artifact_ref_templates, ensure_ascii=False)


def summarize_observations(observations: list[dict[str, Any]]) -> str:
    if not observations:
        return "[]"
    return json.dumps(observations, ensure_ascii=False)


def summarize_role_routing_policy(policy: RoleRoutingPolicy) -> str:
    return json.dumps(policy.as_dict(), ensure_ascii=False)


def build_planner_messages(
    *,
    user_request: str,
    role_registry: RoleRegistry,
    available_skills_by_role: dict[str, list[str]],
    skill_contract_summary: dict[str, dict[str, dict[str, list[str]]]],
    artifact_summary: list[dict[str, str]],
    artifact_refs: list[str],
    artifact_ref_templates: list[dict[str, str]],
    role_routing_policy: RoleRoutingPolicy,
    observation_summary: list[dict[str, Any]],
    budget_snapshot: dict[str, Any],
    planning_iteration: int,
) -> list[dict[str, str]]:
    system_prompt = PLANNER_SYSTEM_PROMPT.format(
        role_registry_summary=summarize_roles(role_registry),
        skill_allowlist_summary=summarize_skill_allowlists(role_registry, available_skills_by_role),
        skill_contract_summary=summarize_skill_contracts(skill_contract_summary),
        artifact_summary=summarize_artifacts(artifact_summary),
        artifact_refs=summarize_artifact_refs(artifact_refs),
        artifact_ref_templates=summarize_artifact_ref_templates(artifact_ref_templates),
        role_routing_summary=summarize_role_routing_policy(role_routing_policy),
        observation_summary=summarize_observations(observation_summary),
        budget_snapshot=json.dumps(budget_snapshot, ensure_ascii=False),
        iteration=planning_iteration,
        planner_output_contract=planner_output_contract(),
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
    role_routing_policy: RoleRoutingPolicy,
    observation_summary: list[dict[str, Any]],
    budget_snapshot: dict[str, Any],
    planning_iteration: int,
    validation_error: str,
    raw_output: str,
) -> list[dict[str, str]]:
    system_prompt = (
        "You are a JSON repair assistant for RoutePlan. "
        "Your only job is to rewrite the previous invalid planner output into valid JSON that matches the exact RoutePlan contract. "
        "Do not add markdown fences. Do not explain. Return corrected JSON only.\n\n"
        f"## Available Roles\n{summarize_roles(role_registry)}\n\n"
        f"## Available Skills per Role\n{summarize_skill_allowlists(role_registry, available_skills_by_role)}\n\n"
        f"## Skill Contracts\n{summarize_skill_contracts(skill_contract_summary)}\n\n"
        f"## Current State\n"
        f"- Artifacts produced so far: {summarize_artifacts(artifact_summary)}\n"
        f"- Exact artifact refs available now: {summarize_artifact_refs(artifact_refs)}\n"
        f"- Deterministic future artifact ref templates: {summarize_artifact_ref_templates(artifact_ref_templates)}\n"
        f"- Role routing policy now: {summarize_role_routing_policy(role_routing_policy)}\n"
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


def build_role_routing_messages(
    *,
    user_request: str,
    role_registry: RoleRegistry,
    available_skills_by_role: dict[str, list[str]],
    artifact_summary: list[dict[str, str]],
    artifact_refs: list[str],
    observation_summary: list[dict[str, Any]],
    budget_snapshot: dict[str, Any],
    planning_iteration: int,
    role_routing_policy: RoleRoutingPolicy,
) -> list[dict[str, str]]:
    system_prompt = ROLE_ROUTER_SYSTEM_PROMPT.format(
        role_registry_summary=summarize_roles(role_registry),
        skill_allowlist_summary=summarize_skill_allowlists(role_registry, available_skills_by_role),
        artifact_summary=summarize_artifacts(artifact_summary),
        artifact_refs=summarize_artifact_refs(artifact_refs),
        observation_summary=summarize_observations(observation_summary),
        budget_snapshot=json.dumps(budget_snapshot, ensure_ascii=False),
        iteration=planning_iteration,
        role_routing_summary=summarize_role_routing_policy(role_routing_policy),
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_request},
    ]
