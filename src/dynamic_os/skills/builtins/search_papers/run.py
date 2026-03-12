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


def _artifact(ctx: SkillContext, payload: dict) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=f"{ctx.node_id}_source_set",
        artifact_type="SourceSet",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload=payload,
        source_inputs=_source_inputs(ctx),
    )


async def run(ctx: SkillContext) -> SkillOutput:
    search_plan = _find_artifact(ctx, "SearchPlan")
    if search_plan is None:
        return SkillOutput(success=False, error="search_papers requires a SearchPlan artifact")

    payload = dict(search_plan.payload)
    queries = [str(item).strip() for item in payload.get("search_queries", []) if str(item).strip()]
    query = queries[0] if queries else ctx.goal
    results = await ctx.tools.search(query, max_results=5)
    artifact = _artifact(
        ctx,
        {
            "query": query,
            "sources": list(results),
            "result_count": len(results),
        },
    )
    return SkillOutput(
        success=True,
        output_artifacts=[artifact],
        metadata={"result_count": len(results)},
    )
