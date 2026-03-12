from __future__ import annotations

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


def _source_inputs(ctx: SkillContext) -> list[str]:
    return [f"artifact:{artifact.artifact_type}:{artifact.artifact_id}" for artifact in ctx.input_artifacts]


async def run(ctx: SkillContext) -> SkillOutput:
    if not ctx.input_artifacts:
        return SkillOutput(success=False, error="review_artifact requires at least one input artifact")

    target = ctx.input_artifacts[0]
    review_text = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": "Review the artifact and return a concise verdict with issues.",
            },
            {
                "role": "user",
                "content": f"{target.artifact_type}: {target.payload}",
            },
        ],
        temperature=0.2,
    )
    verdict = "accept_with_notes" if target.payload else "needs_revision"
    artifact = ArtifactRecord(
        artifact_id=f"{ctx.node_id}_review_verdict",
        artifact_type="ReviewVerdict",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "target_artifact_id": target.artifact_id,
            "target_type": target.artifact_type,
            "verdict": verdict,
            "review": review_text,
            "issues": [] if target.payload else ["artifact payload is empty"],
        },
        source_inputs=_source_inputs(ctx),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])
