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
    plan_text = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": "Turn the goal into a scoped research brief and a small search plan.",
            },
            {"role": "user", "content": ctx.goal},
        ],
        temperature=0.2,
    )
    first_line = next((line.strip() for line in plan_text.splitlines() if line.strip()), ctx.goal.strip())
    search_queries: list[str] = []
    for candidate in [ctx.goal.strip(), first_line]:
        if candidate and candidate not in search_queries:
            search_queries.append(candidate)
    topic_brief = _artifact(
        ctx,
        "TopicBrief",
        "topic_brief",
        {
            "topic": ctx.goal,
            "brief": plan_text,
        },
    )
    search_plan = _artifact(
        ctx,
        "SearchPlan",
        "search_plan",
        {
            "topic": ctx.goal,
            "research_questions": [ctx.goal],
            "search_queries": search_queries,
            "query_routes": {
                query: {
                    "use_academic": True,
                    "use_web": False,
                }
                for query in search_queries
            },
            "plan_text": plan_text,
        },
    )
    return SkillOutput(
        success=True,
        output_artifacts=[topic_brief, search_plan],
        metadata={"query_count": len(search_queries)},
    )
