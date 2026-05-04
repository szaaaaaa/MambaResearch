"""Broken baseline skill used as the input to the demo skill-evolution chain.

Bug: when ``source.get("authors")`` returns a string (paper_search_mcp does
this with ";" separator), the ``for ch in authors`` loop iterates *characters*
instead of authors, so every per-character ``raise`` triggers immediately.
"""

from __future__ import annotations

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


async def run(ctx: SkillContext) -> SkillOutput:
    sources = []
    for art in ctx.input_artifacts:
        if art.artifact_type == "SourceSet":
            sources.extend(art.payload.get("sources", []))

    keywords: list[str] = []
    for source in sources:
        authors = source.get("authors", [])
        # BUG: 没有 normalize，paper_search_mcp 给 string 时按字符迭代
        for author in authors:
            if len(author) < 2:
                raise ValueError(
                    f"author name too short: {author!r} — likely the per-character iteration bug"
                )
            keywords.append(author)

    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="KeywordSet",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={"keywords": keywords},
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])
