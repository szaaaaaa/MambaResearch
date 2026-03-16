from __future__ import annotations

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


def _find_artifact(ctx: SkillContext, artifact_type: str) -> ArtifactRecord | None:
    for artifact in ctx.input_artifacts:
        if artifact.artifact_type == artifact_type:
            return artifact
    return None


def _source_key(source: dict) -> str:
    return str(source.get("paper_id") or source.get("id") or source.get("title") or "").strip()


async def run(ctx: SkillContext) -> SkillOutput:
    source_set = _find_artifact(ctx, "SourceSet")
    if source_set is None:
        return SkillOutput(success=False, error="extract_notes requires a SourceSet artifact")

    payload = dict(source_set.payload)
    sources = [dict(item) for item in payload.get("sources", [])]
    payload_documents = [dict(item) for item in payload.get("documents", [])]
    indexed_documents = {
        str(item.get("paper_id") or item.get("id") or item.get("title") or "").strip(): item
        for item in payload_documents
        if str(item.get("paper_id") or item.get("id") or item.get("title") or "").strip()
    }
    documents = [
        {
            "id": str(item.get("paper_id") or item.get("id") or item.get("title") or f"doc_{index}"),
            "text": str(
                (
                    dict(item.get("retrieved_document") or {}).get("content")
                    if isinstance(item.get("retrieved_document"), dict)
                    else ""
                )
                or indexed_documents.get(_source_key(item), {}).get("content")
                or item.get("content")
                or item.get("abstract")
                or item.get("summary")
                or item.get("title")
                or ""
            ).strip(),
        }
        for index, item in enumerate(sources)
        if str(
            (
                dict(item.get("retrieved_document") or {}).get("content")
                if isinstance(item.get("retrieved_document"), dict)
                else ""
            )
            or indexed_documents.get(_source_key(item), {}).get("content")
            or item.get("content")
            or item.get("abstract")
            or item.get("summary")
            or item.get("title")
            or ""
        ).strip()
    ]
    if not documents:
        return SkillOutput(success=False, error="extract_notes requires retrieved document text")
    warnings: list[str] = []
    try:
        await ctx.tools.index(documents, collection=ctx.run_id)
    except Exception as exc:
        warnings.append(f"document indexing unavailable: {exc}")
    note_summary = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": "Summarize the source set into concise paper notes.",
            },
            {
                "role": "user",
                "content": "\n\n".join(
                    f"{document['id']}\n{document['text'][:1000]}"
                    for document in documents
                ),
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
    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="PaperNotes",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "summary": note_summary,
            "notes": notes,
            "source_count": len(sources),
            "warnings": warnings,
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(
        success=True,
        output_artifacts=[artifact],
        metadata={"note_count": len(notes), "warnings": warnings},
    )
