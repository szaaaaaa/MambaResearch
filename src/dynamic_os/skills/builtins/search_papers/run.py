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


async def run(ctx: SkillContext) -> SkillOutput:
    search_plan = _find_artifact(ctx, "SearchPlan")
    if search_plan is None:
        return SkillOutput(success=False, error="search_papers requires a SearchPlan artifact")

    payload = dict(search_plan.payload)
    queries = [str(item).strip() for item in payload.get("search_queries", []) if str(item).strip()]
    routes = dict(payload.get("query_routes", {})) if isinstance(payload.get("query_routes"), dict) else {}
    resolved_queries = queries or [ctx.goal]
    results: list[dict] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for query in resolved_queries:
        route = dict(routes.get(query, {})) if isinstance(routes.get(query), dict) else {}
        search_result = await ctx.tools.search(query, source=_route_source(route), max_results=5)
        for item in search_result.get("results", []):
            if not isinstance(item, dict):
                continue
            key = str(item.get("paper_id") or item.get("url") or item.get("title") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            results.append(dict(item))
        for warning in search_result.get("warnings", []):
            warning_text = str(warning).strip()
            if warning_text:
                warnings.append(
                    f"{query}: {warning_text}" if len(resolved_queries) > 1 else warning_text
                )
    artifact = _artifact(
        ctx,
        {
            "query": resolved_queries[0],
            "queries": resolved_queries,
            "sources": results,
            "result_count": len(results),
            "warnings": warnings,
        },
    )
    return SkillOutput(
        success=True,
        output_artifacts=[artifact],
        metadata={"result_count": len(results), "warning_count": len(warnings)},
    )


def _route_source(route: dict) -> str:
    if not route:
        return "auto"
    use_academic = bool(route.get("use_academic", True))
    use_web = bool(route.get("use_web", False))
    if use_academic and not use_web:
        return "academic"
    if use_web and not use_academic:
        return "web"
    return "auto"


def _artifact(ctx: SkillContext, payload: dict):
    return make_artifact(
        node_id=ctx.node_id,
        artifact_type="SourceSet",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload=payload,
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
