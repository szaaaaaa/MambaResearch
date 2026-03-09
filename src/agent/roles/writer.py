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


def _extract_report_text(payload: dict[str, Any]) -> str:
    for key in ("report", "content", "markdown", "text", "body"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


class WriterAgent(RoleAgent):
    def __init__(self, *, context: RunContext, state: dict[str, Any]) -> None:
        super().__init__(
            policy=RolePolicy(
                role_id="writer",
                system_prompt="Write the final research report and paper-ready narrative from the available evidence.",
                allowed_skills=["generate_report"],
                max_retries=int(state.get("_cfg", {}).get("reviewer", {}).get("retrieval", {}).get("max_retries", 1)),
                budget_limit_tokens=int(state.get("_cfg", {}).get("budget_guard", {}).get("max_tokens", 500000)),
            ),
            context=context,
            state=state,
        )

    def write(self, artifacts: list[Any]) -> list[Artifact]:
        return self.execute_plan(["generate_report"], artifacts)

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
        if skill_id != "generate_report":
            return

        report_artifact = _latest_artifact_by_types(
            output_artifacts,
            [
                "ResearchReport",
                "FinalReport",
                "ReportDraft",
                "Report",
            ],
        )

        if report_artifact is None:
            report_artifact = next(
                (
                    artifact
                    for artifact in reversed(output_artifacts)
                    if "report" in artifact.artifact_type.lower() or "manuscript" in artifact.artifact_type.lower()
                ),
                None,
            )

        if report_artifact is not None:
            payload = dict(report_artifact.payload)
            report_ns = self.state.setdefault("report", {})
            if isinstance(report_ns, dict):
                report_text = _extract_report_text(payload)
                if report_text:
                    report_ns["report"] = report_text
                if "report_critic" in payload:
                    report_ns["report_critic"] = payload.get("report_critic", {})
                    self.state["report_critic"] = payload.get("report_critic", {})
                if "repair_attempted" in payload:
                    report_ns["repair_attempted"] = bool(payload.get("repair_attempted"))
                    self.state["repair_attempted"] = bool(payload.get("repair_attempted"))
                if "acceptance_metrics" in payload:
                    report_ns["acceptance_metrics"] = dict(payload.get("acceptance_metrics", {}))
                    self.state["acceptance_metrics"] = dict(payload.get("acceptance_metrics", {}))
                report_ns["report_artifact"] = payload

        self.state["status"] = f"Skill {skill_id} completed"
