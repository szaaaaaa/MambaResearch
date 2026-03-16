from __future__ import annotations

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


def _find_artifact(ctx: SkillContext, artifact_type: str) -> ArtifactRecord | None:
    for artifact in ctx.input_artifacts:
        if artifact.artifact_type == artifact_type:
            return artifact
    return None


def _metric_list(metrics: dict) -> list[dict]:
    items: list[dict] = []
    for name, value in metrics.items():
        if isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            continue
        items.append(
            {
                "name": str(name),
                "value": float(value),
                "higher_is_better": "loss" not in str(name).lower(),
            }
        )
    return items


async def run(ctx: SkillContext) -> SkillOutput:
    experiment_plan = _find_artifact(ctx, "ExperimentPlan")
    if experiment_plan is None:
        return SkillOutput(success=False, error="run_experiment requires an ExperimentPlan artifact")

    payload = dict(experiment_plan.payload)
    code = str(payload.get("code") or "").strip()
    language = str(payload.get("language") or "python")
    if not code:
        return SkillOutput(success=False, error="run_experiment requires executable code in ExperimentPlan")
    execution = await ctx.tools.execute_code(code, language=language, timeout_sec=min(ctx.timeout_sec, 60))
    exit_code = execution.get("exit_code")
    if exit_code not in (None, 0):
        return SkillOutput(
            success=False,
            error=f"experiment execution failed with exit_code={exit_code}",
            metadata={"execution": execution},
        )
    metrics = dict(execution.get("metrics", {})) if isinstance(execution.get("metrics", {}), dict) else {}
    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="ExperimentResults",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "status": "completed",
            "execution": execution,
            "metrics": metrics,
            "runs": [
                {
                    "run_id": f"{ctx.node_id}_run_1",
                    "metrics": _metric_list(metrics),
                }
            ],
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(
        success=True,
        output_artifacts=[artifact],
        metadata={"metric_count": len(metrics)},
    )
