from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from src.agent.artifacts.base import Artifact


@dataclass(frozen=True)
class SkillSpec:
    skill_id: str
    purpose: str
    input_artifact_types: list[str] = field(default_factory=list)
    output_artifact_types: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    model_profile: dict[str, Any] = field(default_factory=dict)
    budget_policy: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillResult:
    success: bool
    output_artifacts: list[Artifact] = field(default_factory=list)
    error: str | None = None


class BaseSkill(ABC):
    spec: SkillSpec

    @property
    def skill_id(self) -> str:
        return self.spec.skill_id

    @abstractmethod
    def invoke(self, input_artifacts: list[Any], cfg: dict[str, Any]) -> SkillResult:
        """Execute the skill against the provided inputs."""

    def __call__(self, input_artifacts: list[Any], cfg: dict[str, Any]) -> SkillResult:
        return self.invoke(input_artifacts, cfg)
