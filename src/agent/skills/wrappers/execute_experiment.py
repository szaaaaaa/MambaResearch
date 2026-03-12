from __future__ import annotations

from typing import Any

from src.agent.core.artifact_utils import make_artifact, records_to_artifacts
from src.agent.execution import run_autoresearch
from src.agent.skills.contract import SkillResult, SkillSpec
from src.agent.skills.wrappers import get_base_state, get_cfg_for_stage

SPEC = SkillSpec(
    skill_id="execute_experiment",
    purpose="Execute experiment plans via the configured backend and return ExperimentResults.",
    input_artifact_types=["ExperimentPlan"],
    output_artifact_types=["ExperimentResults"],
)


def _resolve_backend(*, plan: dict[str, Any], cfg: dict[str, Any]) -> str:
    execution_cfg = cfg.get("agent", {}).get("experiment_execution", {})
    configured_backend = ""
    if isinstance(execution_cfg, dict):
        configured_backend = str(execution_cfg.get("backend", "")).strip().lower()
    plan_execution = plan.get("execution", {}) if isinstance(plan.get("execution", {}), dict) else {}
    plan_backend = str(plan_execution.get("backend", "")).strip().lower()
    return plan_backend or configured_backend or "manual"


def handle(input_artifacts: list[Any], cfg: dict[str, Any]) -> SkillResult:
    del input_artifacts

    base_state = get_base_state(cfg)
    stage_cfg = get_cfg_for_stage(cfg)
    experiment_plan = dict(base_state.get("experiment_plan", {}) or {})
    if not experiment_plan:
        return SkillResult(success=False, output_artifacts=[], error="execute_experiment requires experiment_plan in state")

    backend = _resolve_backend(plan=experiment_plan, cfg=stage_cfg)
    if backend != "autoresearch":
        return SkillResult(
            success=False,
            output_artifacts=[],
            error=f"Unsupported experiment execution backend: {backend or 'unknown'}",
        )

    try:
        results_payload = run_autoresearch(
            experiment_plan=experiment_plan,
            cfg=stage_cfg,
            run_id=str(base_state.get("run_id", "") or "manual"),
            topic=str(base_state.get("topic", "") or ""),
        )
    except Exception as exc:
        return SkillResult(success=False, output_artifacts=[], error=str(exc))

    artifact = make_artifact(
        artifact_type="ExperimentResults",
        producer=SPEC.skill_id,
        payload=results_payload,
        source_inputs=[str(base_state.get("topic", "") or "")],
    )
    return SkillResult(success=True, output_artifacts=records_to_artifacts([artifact]))
