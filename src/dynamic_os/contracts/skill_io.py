from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from src.dynamic_os.contracts.artifact import ArtifactRecord

if TYPE_CHECKING:
    from src.dynamic_os.tools.gateway import ToolGateway


@dataclass(frozen=True)
class SkillContext:
    skill_id: str
    role_id: str
    run_id: str
    node_id: str
    goal: str
    input_artifacts: list[ArtifactRecord]
    tools: "ToolGateway"
    config: dict[str, Any] = field(default_factory=dict)
    timeout_sec: int = 120


class SkillOutput(BaseModel):
    model_config = {"frozen": True}

    success: bool
    output_artifacts: list[ArtifactRecord] = Field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
