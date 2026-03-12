from __future__ import annotations

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


def _source_inputs(ctx: SkillContext) -> list[str]:
    return [f"artifact:{artifact.artifact_type}:{artifact.artifact_id}" for artifact in ctx.input_artifacts]


def _artifact(ctx: SkillContext, artifact_type: str, suffix: str, payload: dict) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=f"{ctx.node_id}_{suffix}",
        artifact_type=artifact_type,
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload=payload,
        source_inputs=_source_inputs(ctx),
    )


async def run(ctx: SkillContext) -> SkillOutput:
    artifact_types = [artifact.artifact_type for artifact in ctx.input_artifacts]
    synthesis = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": "Synthesize the inputs into evidence coverage and unresolved gaps.",
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
    evidence_map = _artifact(
        ctx,
        "EvidenceMap",
        "evidence_map",
        {
            "summary": synthesis,
            "source_types": artifact_types,
            "evidence_count": len(ctx.input_artifacts),
        },
    )
    gap_map = _artifact(
        ctx,
        "GapMap",
        "gap_map",
        {
            "summary": f"Open gaps derived from: {synthesis[:240]}",
            "source_types": artifact_types,
            "gap_count": 1 if ctx.input_artifacts else 0,
        },
    )
    return SkillOutput(
        success=True,
        output_artifacts=[evidence_map, gap_map],
        metadata={"input_artifact_count": len(ctx.input_artifacts)},
    )
