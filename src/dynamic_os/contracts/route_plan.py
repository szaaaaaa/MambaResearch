from __future__ import annotations

from collections import deque
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class FailurePolicy(str, Enum):
    replan = "replan"
    skip = "skip"
    abort = "abort"


class RoleId(str, Enum):
    conductor = "conductor"
    researcher = "researcher"
    experimenter = "experimenter"
    analyst = "analyst"
    writer = "writer"
    reviewer = "reviewer"
    hitl = "hitl"


class PlanNode(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    node_id: str = Field(..., pattern=r"^node_[a-z0-9_]+$")
    role: RoleId
    goal: str = Field(..., min_length=1, max_length=500)
    inputs: list[str] = Field(
        default_factory=list,
        description="Artifact references in the form 'artifact:<type>:<id>'.",
    )
    allowed_skills: list[str] = Field(..., min_length=1)
    success_criteria: list[str] = Field(default_factory=list)
    failure_policy: FailurePolicy = FailurePolicy.replan
    expected_outputs: list[str] = Field(default_factory=list)
    needs_review: bool = False
    hitl_question: str = ""


class EdgeCondition(str, Enum):
    on_success = "on_success"
    on_failure = "on_failure"
    always = "always"


class PlanEdge(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    source: str
    target: str
    condition: EdgeCondition = EdgeCondition.on_success


class RoutePlan(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    run_id: str
    planning_iteration: int = Field(..., ge=0)
    horizon: int = Field(..., ge=1, le=8)
    nodes: list[PlanNode] = Field(..., min_length=1, max_length=8)
    edges: list[PlanEdge] = Field(default_factory=list)
    planner_notes: list[str] = Field(default_factory=list)
    terminate: bool = False

    @model_validator(mode="after")
    def validate_graph(self) -> "RoutePlan":
        if self.horizon != len(self.nodes):
            raise ValueError("horizon must equal len(nodes)")

        node_ids = [node.node_id for node in self.nodes]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("node ids must be unique")

        adjacency = {node_id: set() for node_id in node_ids}
        indegree = {node_id: 0 for node_id in node_ids}

        for edge in self.edges:
            if edge.source not in adjacency or edge.target not in adjacency:
                raise ValueError("edge references unknown node id")
            if edge.target not in adjacency[edge.source]:
                adjacency[edge.source].add(edge.target)
                indegree[edge.target] += 1

        ready = deque(node_id for node_id, degree in indegree.items() if degree == 0)
        visited = 0
        while ready:
            node_id = ready.popleft()
            visited += 1
            for target in adjacency[node_id]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)

        if visited != len(node_ids):
            raise ValueError("route plan edges must form a DAG")

        return self
