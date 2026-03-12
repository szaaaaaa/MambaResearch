from __future__ import annotations

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


def _source_inputs(ctx: SkillContext) -> list[str]:
    return [f"artifact:{artifact.artifact_type}:{artifact.artifact_id}" for artifact in ctx.input_artifacts]


async def run(ctx: SkillContext) -> SkillOutput:
    report_text = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": "Draft a concise research report grounded only in the provided artifacts.",
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
        artifact_id=f"{ctx.node_id}_research_report",
        artifact_type="ResearchReport",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "report": report_text,
            "artifact_count": len(ctx.input_artifacts),
        },
        source_inputs=_source_inputs(ctx),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])
