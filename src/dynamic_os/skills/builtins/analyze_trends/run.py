from __future__ import annotations

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput, serialize_payload as _serialize_payload


async def run(ctx: SkillContext) -> SkillOutput:
    if not ctx.input_artifacts:
        return SkillOutput(success=False, error="analyze_trends requires at least one input artifact")

    artifact_text = "\n\n".join(
        f"{artifact.artifact_type} ({artifact.artifact_id}):\n{_serialize_payload(artifact)}"
        for artifact in ctx.input_artifacts
    )

    summary = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a research trend analyst. Identify temporal trends from the provided "
                    "research artifacts. Focus on: (1) emerging topics gaining traction, "
                    "(2) declining topics losing interest, (3) key inflection points where "
                    "research direction shifted, (4) methodological evolution over time. "
                    "Be specific and cite evidence from the provided data."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Goal: {ctx.user_request or ctx.goal}\n\n"
                    f"Artifacts:\n{artifact_text}"
                ),
            },
        ],
        temperature=0.3,
    )

    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="TrendAnalysis",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "summary": summary,
            "trends": [],
            "source_count": len(ctx.input_artifacts),
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])
