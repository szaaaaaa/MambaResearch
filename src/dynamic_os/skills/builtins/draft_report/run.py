from __future__ import annotations

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


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
    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="ResearchReport",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "report": report_text,
            "artifact_count": len(ctx.input_artifacts),
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])
