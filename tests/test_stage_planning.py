from __future__ import annotations

import json
import unittest

from src.agent.stages.planning import plan_research


class StagePlanningTest(unittest.TestCase):
    def test_plan_research_raises_when_json_invalid(self) -> None:
        state = {
            "topic": "retrieval augmented generation benchmark",
            "iteration": 0,
            "_cfg": {"agent": {"max_queries_per_iteration": 3}},
        }

        def parse_json(_: str) -> dict[str, object]:
            raise json.JSONDecodeError("bad", "bad", 0)

        with self.assertRaisesRegex(RuntimeError, "plan_research returned invalid JSON"):
            plan_research(
                state,
                state_view=lambda x: x,
                get_cfg=lambda x: x.get("_cfg", {}),
                load_budget_and_scope=lambda _state, _cfg: (
                    {"intent": "survey", "allowed_sections": ["Introduction"]},
                    {"max_research_questions": 3, "max_sections": 5, "max_references": 20},
                ),
                ns=lambda x: x,
                llm_call=lambda *args, **kwargs: "not-json",
                parse_json=parse_json,
                compress_findings_for_context=lambda *args, **kwargs: "",
                expand_query_set=lambda **kwargs: [],
                academic_sources_enabled=lambda cfg: True,
                web_sources_enabled=lambda cfg: True,
                route_query=lambda query, cfg: {"use_academic": True, "use_web": True},
            )

    def test_plan_research_applies_focus_and_routing(self) -> None:
        state = {
            "topic": "RAG",
            "iteration": 1,
            "findings": ["old finding"],
            "gaps": ["missing evaluation"],
            "search_queries": ["old query"],
            "_focus_research_questions": ["rq2"],
            "_cfg": {
                "agent": {
                    "max_queries_per_iteration": 2,
                    "memory": {"max_findings_for_context": 2, "max_context_chars": 200},
                    "query_rewrite": {"min_per_rq": 1, "max_per_rq": 1, "max_total_queries": 4},
                }
            },
        }
        parse_result = {
            "research_questions": ["rq1", "rq2"],
            "academic_queries": ["aq1", "aq2"],
            "web_queries": ["wq1"],
        }
        captured: dict[str, object] = {}

        def expand_query_set(**kwargs):
            captured["rq_list"] = kwargs["rq_list"]
            return [
                {"query": "aq2", "type": "precision"},
                {"query": "rq2 survey", "type": "recall"},
            ]

        def route_query(query: str, cfg: dict[str, object]) -> dict[str, object]:
            if query == "aq2":
                return {"use_academic": False, "use_web": True}
            return {"use_academic": True, "use_web": True}

        out = plan_research(
            state,
            state_view=lambda x: x,
            get_cfg=lambda x: x.get("_cfg", {}),
            load_budget_and_scope=lambda _state, _cfg: (
                {"intent": "survey", "allowed_sections": ["Introduction", "Findings"]},
                {"max_research_questions": 2, "max_sections": 5, "max_references": 20},
            ),
            ns=lambda x: x,
            llm_call=lambda *args, **kwargs: "unused",
            parse_json=lambda _: parse_result,
            compress_findings_for_context=lambda *args, **kwargs: "summary",
            expand_query_set=expand_query_set,
            academic_sources_enabled=lambda cfg: True,
            web_sources_enabled=lambda cfg: True,
            route_query=route_query,
        )

        self.assertEqual(captured["rq_list"], ["rq2"])
        self.assertEqual(out["memory_summary"], "summary")
        self.assertEqual(out["_academic_queries"], ["rq2 survey"])
        self.assertEqual(out["_web_queries"], ["rq2 survey", "wq1", "aq2"])


if __name__ == "__main__":
    unittest.main()
