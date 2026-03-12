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
        return SkillOutput(success=False, error="extract_notes requires a SourceSet artifact")

    payload = dict(source_set.payload)
    sources = [dict(item) for item in payload.get("sources", [])]
    documents = [
        {
            "id": str(item.get("paper_id") or item.get("id") or item.get("title") or f"doc_{index}"),
            "text": str(
                item.get("content")
                or item.get("abstract")
                or item.get("summary")
                or item.get("title")
                or ""
            ),
        }
        for index, item in enumerate(sources)
    ]
    await ctx.tools.index(documents, collection=ctx.run_id)
    note_summary = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": "Summarize the source set into concise paper notes.",
            },
            {
                "role": "user",
                "content": "\n".join(str(item.get("title") or item.get("id") or "") for item in sources),
            },
        ],
        temperature=0.2,
    )
    notes = [
        {
            "source_id": document["id"],
            "summary": document["text"][:240],
        }
        for document in documents
    ]
    artifact = ArtifactRecord(
        artifact_id=f"{ctx.node_id}_paper_notes",
        artifact_type="PaperNotes",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "summary": note_summary,
            "notes": notes,
            "source_count": len(sources),
        },
        source_inputs=_source_inputs(ctx),
    )
    return SkillOutput(
        success=True,
        output_artifacts=[artifact],
        metadata={"note_count": len(notes)},
    )
