from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class BaseEvent(BaseModel):
    model_config = {"frozen": True}

    ts: str
    run_id: str
    type: str


class PlanUpdateEvent(BaseEvent):
    type: Literal["plan_update"] = "plan_update"
    planning_iteration: int
    plan: dict[str, Any]


class NodeStatusEvent(BaseEvent):
    type: Literal["node_status"] = "node_status"
    node_id: str
    role: str
    status: str


class SkillInvokeEvent(BaseEvent):
    type: Literal["skill_invoke"] = "skill_invoke"
    node_id: str
    skill_id: str
    phase: str


class ToolInvokeEvent(BaseEvent):
    type: Literal["tool_invoke"] = "tool_invoke"
    node_id: str
    skill_id: str
    tool_id: str
    phase: str


class ObservationEvent(BaseEvent):
    type: Literal["observation"] = "observation"
    observation: dict[str, Any]


class ReplanEvent(BaseEvent):
    type: Literal["replan"] = "replan"
    reason: str
    previous_iteration: int
    new_iteration: int


class ArtifactEvent(BaseEvent):
    type: Literal["artifact_created"] = "artifact_created"
    artifact_id: str
    artifact_type: str
    producer_role: str
    producer_skill: str


class PolicyBlockEvent(BaseEvent):
    type: Literal["policy_block"] = "policy_block"
    blocked_action: str
    reason: str


class RunTerminateEvent(BaseEvent):
    type: Literal["run_terminate"] = "run_terminate"
    reason: str
    final_artifacts: list[str]


class HitlRequestEvent(BaseEvent):
    type: Literal["hitl_request"] = "hitl_request"
    node_id: str
    question: str
    context: str


class HitlResponseEvent(BaseEvent):
    type: Literal["hitl_response"] = "hitl_response"
    node_id: str
    response: str

