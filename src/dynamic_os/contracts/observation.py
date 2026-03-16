from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from src.dynamic_os.contracts.route_plan import RoleId


class NodeStatus(str, Enum):
    success = "success"
    partial = "partial"
    failed = "failed"
    needs_replan = "needs_replan"
    skipped = "skipped"


class ErrorType(str, Enum):
    tool_failure = "tool_failure"
    skill_error = "skill_error"
    timeout = "timeout"
    policy_block = "policy_block"
    input_missing = "input_missing"
    llm_error = "llm_error"
    none = "none"


class Observation(BaseModel):
    model_config = {"frozen": True}

    node_id: str
    role: RoleId | Literal["planner"]
    status: NodeStatus
    error_type: ErrorType = ErrorType.none
    what_happened: str = ""
    what_was_tried: list[str] = Field(default_factory=list)
    suggested_options: list[str] = Field(default_factory=list)
    recommended_action: str = ""
    produced_artifacts: list[str] = Field(
        default_factory=list,
        description="Artifact references in the form 'artifact:<type>:<id>'.",
    )
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    duration_ms: float = 0.0
