from __future__ import annotations

import unittest
from unittest.mock import patch

from src.agent import nodes
from src.agent.core.executor import TaskResult
from src.agent.stages import analysis, evaluation, planning, retrieval


class NodesFlowTest(unittest.TestCase):
    def test_nodes_reexport_stage_functions(self) -> None:
        self.assertIs(nodes.plan_research, planning.plan_research)
        self.assertIs(nodes.fetch_sources, retrieval.fetch_sources)
        self.assertIs(nodes.analyze_sources, analysis.analyze_sources)
        self.assertIs(nodes.evaluate_progress, evaluation.evaluate_progress)

    def test_plan_research_via_nodes_uses_stage_impl(self) -> None:
        state = {
            "topic": "retrieval augmented generation benchmark",
            "iteration": 0,
            "_cfg": {"agent": {"max_queries_per_iteration": 3}},
        }
        with patch("src.agent.stages.planning._runtime_llm_call", return_value="not-json"):
            out = nodes.plan_research(state)

        self.assertEqual(len(out.get("research_questions", [])), 1)
        self.assertTrue(out.get("_academic_queries", []))
        self.assertTrue(out.get("_web_queries", []))

    def test_fetch_sources_via_nodes_uses_stage_impl(self) -> None:
        state = {
            "topic": "retrieval augmented generation",
            "search_queries": ["rag retrieval"],
            "_academic_queries": ["qa", "qb"],
            "_web_queries": ["qw"],
            "query_routes": {
                "qa": {"use_academic": True, "use_web": True},
                "qb": {"use_academic": False, "use_web": True},
                "qw": {"use_web": True},
            },
            "papers": [{"uid": "p-old"}],
            "web_sources": [{"uid": "w-old"}],
            "_cfg": {"agent": {"topic_filter": {"min_keyword_hits": 1}}},
        }
        provider_result = {
            "papers": [
                {"uid": "p-new", "title": "RAG retrieval methods", "abstract": "retrieval quality"},
                {"uid": "p-old", "title": "duplicate", "abstract": "retrieval"},
            ],
            "web_sources": [
                {"uid": "w-new", "title": "RAG in production", "snippet": "retrieval and generation"},
                {"uid": "w-old", "title": "duplicate web", "snippet": "retrieval"},
            ],
        }
        with patch(
            "src.agent.stages.retrieval._default_dispatch",
            return_value=TaskResult(success=True, data=provider_result),
        ) as dispatch_mock:
            out = nodes.fetch_sources(state)

        self.assertEqual([p["uid"] for p in out.get("papers", [])], ["p-old", "p-new"])
        self.assertEqual([w["uid"] for w in out.get("web_sources", [])], ["w-old", "w-new"])
        task = dispatch_mock.call_args.args[0]
        self.assertEqual(task.params["academic_queries"], ["qa"])
        self.assertEqual(task.params["web_queries"], ["qw", "qa", "qb"])

    def test_fetch_sources_wrapper_keeps_failure_shape(self) -> None:
        state = {
            "topic": "retrieval augmented generation",
            "search_queries": ["rag retrieval"],
            "_academic_queries": ["qa"],
            "_web_queries": ["qw"],
            "query_routes": {},
            "papers": [],
            "web_sources": [],
            "_cfg": {},
        }
        with patch(
            "src.agent.stages.retrieval._default_dispatch",
            return_value=TaskResult(success=False, error="backend down"),
        ):
            out = nodes.fetch_sources(state)

        self.assertEqual(out.get("papers", []), [])
        self.assertEqual(out.get("web_sources", []), [])
        self.assertIn("Fetch failed: backend down", out["status"])

    def test_evaluate_progress_via_nodes_uses_stage_impl(self) -> None:
        state = {
            "topic": "x",
            "iteration": 0,
            "max_iterations": 3,
            "papers": [{"uid": "p1"}],
            "web_sources": [],
            "research_questions": ["rq1"],
            "gaps": [],
            "synthesis": "s",
            "evidence_audit_log": [{"research_question": "rq1", "gaps": ["ab_evidence_below_2"]}],
            "_cfg": {},
        }
        with patch("src.agent.stages.evaluation._runtime_llm_call", return_value='{"should_continue": false, "gaps": []}'):
            out = nodes.evaluate_progress(state)

        self.assertTrue(out["should_continue"])
        self.assertTrue(any("Evidence gap in RQ: rq1" in g for g in out.get("gaps", [])))


if __name__ == "__main__":
    unittest.main()
