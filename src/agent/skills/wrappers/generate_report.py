from __future__ import annotations

from typing import Any

from src.agent.core.artifact_utils import make_artifact, records_to_artifacts
from src.agent.skills.contract import SkillResult, SkillSpec
from src.agent.skills.wrappers import get_artifact_records, get_base_state, get_cfg_for_stage
from src.agent.stages.reporting import generate_report as run_generate_report

SPEC = SkillSpec(
    skill_id="generate_report",
    purpose="Generate the final report from the current research state.",
    input_artifact_types=[],
    output_artifact_types=["ResearchReport"],
)


def handle(input_artifacts: list[Any], cfg: dict[str, Any]) -> SkillResult:
    del input_artifacts

    base_state = get_base_state(cfg)
    state = dict(base_state)
    state["artifacts"] = get_artifact_records(base_state)
    state["_cfg"] = get_cfg_for_stage(cfg)

    update = run_generate_report(state)
    report_text = str(update.get("report") or "").strip()
    if not report_text:
        report_payload = update.get("report", {})
        if isinstance(report_payload, dict):
            report_text = str(report_payload.get("report") or "").strip()
    if not report_text:
        return SkillResult(success=False, output_artifacts=[], error="generate_report produced no report text")

    payload = {
        "report": report_text,
        "report_critic": dict(update.get("report_critic", {}) or {}),
        "repair_attempted": bool(update.get("repair_attempted", False)),
        "acceptance_metrics": dict(update.get("acceptance_metrics", {}) or {}),
        "status": str(update.get("status") or ""),
    }
    artifact = make_artifact(
        artifact_type="ResearchReport",
        producer=SPEC.skill_id,
        payload=payload,
        source_inputs=[],
    )
    return SkillResult(success=True, output_artifacts=records_to_artifacts([artifact]))
