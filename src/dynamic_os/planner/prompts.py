from __future__ import annotations

import json
from typing import Any

from src.dynamic_os.roles.registry import RoleRegistry


PLANNER_SYSTEM_PROMPT = """You are the planner for a research operating system with six execution roles.

Your job: given a user request and current execution state, produce a small
local execution DAG, typically 2-4 nodes. You do NOT plan the full run - only the next
meaningful segment.

## Available Roles
{role_registry_summary}

## Available Skills per Role
{skill_allowlist_summary}

## Current State
- Artifacts produced so far: {artifact_summary}
- Latest observations: {observation_summary}
- Budget usage: {budget_snapshot}
- Planning iteration: {iteration}

## Rules
1. Select the smallest set of roles needed for the next step.
2. Each node must specify allowed_skills from that role's allowlist.
3. Set needs_review=true only when output uncertainty is high, evidence
   conflicts, or a critical deliverable is about to be produced.
4. Set terminate=true when the user goal is fully satisfied.
5. Output valid JSON matching the RoutePlan schema.
"""


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


def summarize_artifacts(artifacts: list[dict[str, str]]) -> str:
    if not artifacts:
        return "[]"
    return json.dumps(artifacts, ensure_ascii=False)


def summarize_observations(observations: list[dict[str, Any]]) -> str:
    if not observations:
        return "[]"
    return json.dumps(observations, ensure_ascii=False)


def build_planner_messages(
    *,
    user_request: str,
    role_registry: RoleRegistry,
    available_skills_by_role: dict[str, list[str]],
    artifact_summary: list[dict[str, str]],
    observation_summary: list[dict[str, Any]],
    budget_snapshot: dict[str, Any],
    planning_iteration: int,
) -> list[dict[str, str]]:
    system_prompt = PLANNER_SYSTEM_PROMPT.format(
        role_registry_summary=summarize_roles(role_registry),
        skill_allowlist_summary=summarize_skill_allowlists(role_registry, available_skills_by_role),
        artifact_summary=summarize_artifacts(artifact_summary),
        observation_summary=summarize_observations(observation_summary),
        budget_snapshot=json.dumps(budget_snapshot, ensure_ascii=False),
        iteration=planning_iteration,
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_request},
    ]
