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


def _latest_artifact_by_types(artifacts: list[Artifact], artifact_types: list[str]) -> Artifact | None:
    for artifact_type in artifact_types:
        artifact = _latest_artifact(artifacts, artifact_type)
        if artifact is not None:
            return artifact
    return None


class AnalystAgent(RoleAgent):
    def __init__(self, *, context: RunContext, state: dict[str, Any]) -> None:
        super().__init__(
            policy=RolePolicy(
                role_id="analyst",
                system_prompt="Analyze experiment results and extract performance insights from completed runs.",
                allowed_skills=["analyze_results"],
                max_retries=int(state.get("_cfg", {}).get("reviewer", {}).get("retrieval", {}).get("max_retries", 1)),
                budget_limit_tokens=int(state.get("_cfg", {}).get("budget_guard", {}).get("max_tokens", 500000)),
            ),
            context=context,
            state=state,
        )

    def analyze(self, artifacts: list[Any]) -> list[Artifact]:
        return self.execute_plan(["analyze_results"], artifacts)

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
        if skill_id != "analyze_results":
            return

        analysis_artifact = _latest_artifact_by_types(
            output_artifacts,
            [
                "ExperimentAnalysis",
                "ResultsAnalysis",
                "PerformanceAnalysis",
                "AnalysisReport",
            ],
        )
        metrics_artifact = _latest_artifact_by_types(
            output_artifacts,
            [
                "PerformanceMetrics",
                "MetricsSummary",
            ],
        )

        if analysis_artifact is None:
            analysis_artifact = next(
                (artifact for artifact in reversed(output_artifacts) if "analysis" in artifact.artifact_type.lower()),
                None,
            )

        if metrics_artifact is None:
            metrics_artifact = next(
                (artifact for artifact in reversed(output_artifacts) if "metric" in artifact.artifact_type.lower()),
                None,
            )

        if analysis_artifact is not None:
            payload = dict(analysis_artifact.payload)
            self.state["result_analysis"] = payload
            if "performance_metrics" in payload:
                self.state["performance_metrics"] = payload.get("performance_metrics", {})

        if metrics_artifact is not None:
            self.state["performance_metrics"] = dict(metrics_artifact.payload)

        self.state["status"] = f"Skill {skill_id} completed"
