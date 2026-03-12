from __future__ import annotations

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


def _source_inputs(ctx: SkillContext) -> list[str]:
    return [f"artifact:{artifact.artifact_type}:{artifact.artifact_id}" for artifact in ctx.input_artifacts]


async def run(ctx: SkillContext) -> SkillOutput:
    plan_text = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": "Design a minimal experiment plan with measurable outputs.",
            },
            {
                "role": "user",
                "content": "\n".join(
                    f"{artifact.artifact_type}: {artifact.payload}"
                    for artifact in ctx.input_artifacts
                )
                or ctx.goal,
            },
        ],
        temperature=0.2,
    )
    artifact = ArtifactRecord(
        artifact_id=f"{ctx.node_id}_experiment_plan",
        artifact_type="ExperimentPlan",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "plan": plan_text,
            "language": "python",
            "code": "metrics = {'accuracy': 0.91, 'latency_ms': 120}\nprint(metrics)",
        },
        source_inputs=_source_inputs(ctx),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])
