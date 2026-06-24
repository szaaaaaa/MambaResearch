from __future__ import annotations

import asyncio

from src.dynamic_os.artifact_refs import make_artifact
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext
from src.dynamic_os.skills.builtins.search_papers.run import run as search_papers_run


class _RecordingTools:
    def __init__(self) -> None:
        self.search_calls: list[str] = []

    async def search(self, query: str, **kwargs):
        del kwargs
        self.search_calls.append(query)
        return {"results": []}


def test_search_papers_rejects_empty_search_plan_queries() -> None:
    tools = _RecordingTools()
    search_plan = make_artifact(
        node_id="node_plan",
        artifact_type="SearchPlan",
        producer_role=RoleId.researcher,
        producer_skill="plan_research",
        payload={"search_queries": []},
    )
    ctx = SkillContext(
        skill_id="search_papers",
        role_id="researcher",
        run_id="run_empty_search_queries",
        node_id="node_search",
        goal="write a review report",
        input_artifacts=[search_plan],
        tools=tools,
        user_request="fallback should not be used",
    )

    output = asyncio.run(search_papers_run(ctx))

    assert output.success is False
    assert output.output_artifacts == []
    assert "non-empty SearchPlan.search_queries" in str(output.error)
    assert tools.search_calls == []
