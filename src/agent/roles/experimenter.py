from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.agent.artifacts.base import Artifact
from src.agent.roles.base import RoleAgent, RolePolicy

if TYPE_CHECKING:
    from src.agent.runtime.context import RunContext


def _latest_artifact(artifacts: list[Artifact], artifact_type: str) -> Artifact | None:
    matches = [artifact for artifact in artifacts if artifact.artifact_type == artifact_type]
    if not matches:
        return None
    return matches[-1]


class ExperimenterAgent(RoleAgent):
    def __init__(self, *, context: RunContext, state: dict[str, Any]) -> None:
        super().__init__(
            policy=RolePolicy(
                role_id="experimenter",
                system_prompt="Design experiments and execute configured experiment backends from synthesized research.",
                allowed_skills=["design_experiment", "execute_experiment"],
                max_retries=int(state.get("_cfg", {}).get("reviewer", {}).get("retrieval", {}).get("max_retries", 1)),
                budget_limit_tokens=int(state.get("_cfg", {}).get("budget_guard", {}).get("max_tokens", 500000)),
            ),
            context=context,
            state=state,
        )

    def design(self, artifacts: list[Any]) -> list[Artifact]:
        route_mode = str(self.state.get("route_mode", "") or "").strip().lower()
        skill_ids = ["design_experiment"]
        if route_mode == "experiment_execution":
            skill_ids.append("execute_experiment")
        return self.execute_plan(skill_ids, artifacts)

    def execute_plan(self, skill_ids: list[str], artifacts: list[Any]) -> list[Artifact]:
        current_artifacts = [artifact for artifact in artifacts if isinstance(artifact, Artifact)]
        for skill_id in skill_ids:
            output_artifacts = self.execute(skill_id, current_artifacts)
            current_artifacts.extend(output_artifacts)
            self.state["_artifact_objects"] = current_artifacts
            self.state["artifacts"] = [artifact.to_record() for artifact in current_artifacts]
            self._apply_skill_outputs(skill_id, output_artifacts)
        return current_artifacts

    def _apply_skill_outputs(self, skill_id: str, output_artifacts: list[Artifact]) -> None:
        if skill_id not in {"design_experiment", "execute_experiment"}:
            return

        experiment_plan = _latest_artifact(output_artifacts, "ExperimentPlan")
        experiment_results = _latest_artifact(output_artifacts, "ExperimentResults")

        if experiment_plan is not None:
            self.state["experiment_plan"] = dict(experiment_plan.payload)

        if experiment_results is not None:
            payload = dict(experiment_results.payload)
            self.state["experiment_results"] = payload
            status = str(payload.get("status", "")).strip().lower()
            if status:
                self.state["await_experiment_results"] = status != "validated"

        self.state["status"] = f"Skill {skill_id} completed"
