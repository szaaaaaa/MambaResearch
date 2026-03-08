from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.agent.artifacts.base import Artifact
from src.agent.core.config import apply_role_llm_overrides
from src.agent.plugins.bootstrap import ensure_plugins_registered
from src.agent.skills.registry import get_skill_registry

if TYPE_CHECKING:
    from src.agent.runtime.context import RunContext


@dataclass(frozen=True)
class RolePolicy:
    role_id: str
    system_prompt: str
    allowed_skills: list[str]
    max_retries: int
    budget_limit_tokens: int


class RoleAgent:
    def __init__(self, *, policy: RolePolicy, context: RunContext, state: dict[str, Any]) -> None:
        self.policy = policy
        self.context = context
        self.state = state

    def plan(self, context: RunContext) -> list[str]:
        return []

    def execute(self, skill_id: str, artifacts: list[Any]) -> list[Artifact]:
        if skill_id not in self.policy.allowed_skills:
            raise ValueError(f"Skill {skill_id} is not allowed for role {self.policy.role_id}")

        ensure_plugins_registered()
        cfg = apply_role_llm_overrides(dict(self.state.get("_cfg", {})), self.policy.role_id)
        cfg["_active_role"] = self.policy.role_id
        cfg["_skill_state"] = self.state
        result = get_skill_registry().invoke(skill_id, list(artifacts), cfg)
        if not result.success:
            raise RuntimeError(result.error or f"Skill {skill_id} failed")

        output_artifacts = list(result.output_artifacts)
        for artifact in output_artifacts:
            self.context.artifact_registry.save(artifact)
        return output_artifacts
