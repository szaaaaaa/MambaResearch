from __future__ import annotations

from src.dynamic_os.contracts.observation import NodeStatus, Observation


def assess_review_need(
    *,
    uncertainty_high: bool = False,
    evidence_conflicts: bool = False,
    critical_deliverable: bool = False,
    execution_blocked: bool = False,
) -> bool:
    return uncertainty_high or evidence_conflicts or critical_deliverable or execution_blocked


def replan_from_observation(observation: Observation | None) -> bool:
    if observation is None:
        return False
    return observation.status in {
        NodeStatus.partial,
        NodeStatus.failed,
        NodeStatus.needs_replan,
    }


def decide_termination(artifact_summaries: list[dict[str, str]]) -> bool:
    final_artifact_types = {"ResearchReport", "ReviewVerdict"}
    return any(artifact.get("artifact_type") in final_artifact_types for artifact in artifact_summaries)

