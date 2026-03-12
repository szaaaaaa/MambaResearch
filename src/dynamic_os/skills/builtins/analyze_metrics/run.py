from __future__ import annotations

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


def _find_artifact(ctx: SkillContext, artifact_type: str) -> ArtifactRecord | None:
    for artifact in ctx.input_artifacts:
        if artifact.artifact_type == artifact_type:
            return artifact
    return None


def _source_inputs(ctx: SkillContext) -> list[str]:
    return [f"artifact:{artifact.artifact_type}:{artifact.artifact_id}" for artifact in ctx.input_artifacts]


async def run(ctx: SkillContext) -> SkillOutput:
    experiment_results = _find_artifact(ctx, "ExperimentResults")
    if experiment_results is None:
        return SkillOutput(success=False, error="analyze_metrics requires an ExperimentResults artifact")

    payload = dict(experiment_results.payload)
    metrics = dict(payload.get("metrics", {})) if isinstance(payload.get("metrics", {}), dict) else {}
    analysis_text = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": "Analyze the experiment results into concise findings.",
            },
            {"role": "user", "content": str(payload)},
        ],
        temperature=0.2,
    )
    analysis = ArtifactRecord(
        artifact_id=f"{ctx.node_id}_experiment_analysis",
        artifact_type="ExperimentAnalysis",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "summary": analysis_text,
            "result_status": str(payload.get("status") or ""),
            "metrics": metrics,
        },
        source_inputs=_source_inputs(ctx),
    )
    performance_metrics = ArtifactRecord(
        artifact_id=f"{ctx.node_id}_performance_metrics",
        artifact_type="PerformanceMetrics",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "metric_count": len(metrics),
            "metrics": metrics,
        },
        source_inputs=_source_inputs(ctx),
    )
    return SkillOutput(
        success=True,
        output_artifacts=[analysis, performance_metrics],
        metadata={"metric_count": len(metrics)},
    )
