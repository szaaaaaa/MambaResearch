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


def _retrieve_query(source: dict, fallback: str) -> str:
    parts = [
        str(source.get("title") or "").strip(),
        str(source.get("paper_id") or "").strip(),
        str(source.get("abstract") or "").strip(),
        str(source.get("url") or source.get("pdf_url") or "").strip(),
        fallback.strip(),
    ]
    return "\n".join(part for part in parts if part)


async def run(ctx: SkillContext) -> SkillOutput:
    source_set = _find_artifact(ctx, "SourceSet")
    if source_set is None:
        return SkillOutput(success=False, error="fetch_fulltext requires a SourceSet artifact")

    payload = dict(source_set.payload)
    sources = [dict(item) for item in payload.get("sources", [])]
    query = str(payload.get("query") or ctx.goal).strip() or ctx.goal
    documents: list[dict] = []
    enriched_sources: list[dict] = []
    warnings: list[str] = []
    for source in sources:
        retrieved = await ctx.tools.retrieve(
            _retrieve_query(source, query),
            top_k=1,
            filters={
                "paper_id": str(source.get("paper_id") or ""),
                "url": str(source.get("url") or source.get("pdf_url") or ""),
                "pdf_url": str(source.get("pdf_url") or ""),
                "title": str(source.get("title") or ""),
            },
        )
        item = dict(source)
        if retrieved:
            document = dict(retrieved[0])
            item["retrieved_document"] = document
            item["content"] = str(document.get("content") or item.get("content") or item.get("abstract") or "").strip()
            documents.append(document)
        elif str(item.get("content") or item.get("abstract") or "").strip():
            fallback_text = str(item.get("content") or item.get("abstract") or "").strip()
            document = {
                "paper_id": str(item.get("paper_id") or ""),
                "title": str(item.get("title") or ""),
                "content": fallback_text,
                "source": "artifact_fallback",
                "fetch_method": "artifact_payload",
            }
            item["retrieved_document"] = document
            item["content"] = fallback_text
            documents.append(document)
        else:
            label = str(item.get("title") or item.get("paper_id") or item.get("url") or "unknown source").strip()
            warnings.append(f"no retrievable content for {label}")
        enriched_sources.append(item)
    fetched_count = len(documents)
    if fetched_count == 0:
        return SkillOutput(success=False, error="fetch_fulltext could not retrieve any document text")
    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="SourceSet",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "query": query,
            "sources": enriched_sources,
            "documents": documents,
            "fetched": fetched_count == len(sources),
            "fetched_count": fetched_count,
            "warnings": warnings,
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(
        success=True,
        output_artifacts=[artifact],
        metadata={"document_count": fetched_count},
    )
