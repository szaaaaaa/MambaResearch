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
    source_set = _find_artifact(ctx, "SourceSet")
    if source_set is None:
        return SkillOutput(success=False, error="fetch_fulltext requires a SourceSet artifact")

    payload = dict(source_set.payload)
    sources = list(payload.get("sources", []))
    query = str(payload.get("query") or ctx.goal).strip() or ctx.goal
    documents = await ctx.tools.retrieve(
        query,
        top_k=max(1, min(5, len(sources) or 3)),
        filters={"source_count": len(sources)},
    )
    enriched_sources = []
    for index, source in enumerate(sources):
        item = dict(source)
        if index < len(documents):
            item["retrieved_document"] = documents[index]
        enriched_sources.append(item)
    artifact = ArtifactRecord(
        artifact_id=f"{ctx.node_id}_source_set",
        artifact_type="SourceSet",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "query": query,
            "sources": enriched_sources or sources,
            "documents": list(documents),
            "fetched": True,
        },
        source_inputs=_source_inputs(ctx),
    )
    return SkillOutput(
        success=True,
        output_artifacts=[artifact],
        metadata={"document_count": len(documents)},
    )
