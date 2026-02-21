from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from src.agent import nodes
from src.agent.core.executor import TaskResult
from src.agent.core.state_access import sget


class NodesFlowTest(unittest.TestCase):
    class _Guard:
        def check(self):
            return {
                "exceeded": True,
                "reason": "Token budget exhausted: 100/100",
                "usage": {"tokens_used": 100, "api_calls": 10, "elapsed_sec": 1.0},
            }

    def test_plan_research_fallback_when_json_invalid(self) -> None:
        state = {
            "topic": "retrieval augmented generation benchmark",
            "iteration": 0,
            "_cfg": {"agent": {"max_queries_per_iteration": 3}},
        }
        with patch("src.agent.nodes._llm_call", return_value="not-json"):
            out = nodes.plan_research(state)

        rqs = sget(out, "research_questions", [])
        self.assertEqual(len(rqs), 1)
        self.assertIn("retrieval augmented generation benchmark", rqs[0].lower())
        self.assertTrue(sget(out, "_academic_queries", []))
        self.assertTrue(sget(out, "_web_queries", []))
        self.assertTrue(isinstance(sget(out, "query_routes", {}), dict))

    def test_plan_research_applies_limits_and_dynamic_routes(self) -> None:
        state = {
            "topic": "RAG",
            "iteration": 0,
            "_cfg": {
                "agent": {
                    "max_queries_per_iteration": 2,
                    "budget": {"max_research_questions": 1, "max_sections": 5, "max_references": 20},
                    "dynamic_retrieval": {"simple_query_academic": False},
                }
            },
        }
        llm_json = (
            '{"research_questions": ["q1", "q2"], '
            '"academic_queries": ["what is rag", "rag benchmark", "third"], '
            '"web_queries": ["what is rag", "extra", "third"]}'
        )
        with patch("src.agent.nodes._llm_call", return_value=llm_json):
            out = nodes.plan_research(state)

        year = datetime.now().year
        self.assertEqual(sget(out, "research_questions", []), ["q1"])
        self.assertEqual(
            sget(out, "search_queries", []),
            [
                "what is rag",
                "rag benchmark",
                "extra",
                "q1",
                '"q1"',
                f"q1 {year-2} {year-1} {year}",
                "q1 benchmark evaluation ablation",
                "q1 survey systematic review",
            ],
        )
        self.assertEqual(
            sget(out, "_academic_queries", []),
            [
                "rag benchmark",
                "extra",
                "q1",
                '"q1"',
                f"q1 {year-2} {year-1} {year}",
                "q1 benchmark evaluation ablation",
                "q1 survey systematic review",
            ],
        )
        self.assertEqual(
            sget(out, "_web_queries", []),
            [
                "q1 benchmark evaluation ablation",
                "q1 survey systematic review",
                "what is rag",
                "extra",
                "rag benchmark",
                "q1",
                '"q1"',
                f"q1 {year-2} {year-1} {year}",
            ],
        )

    def test_fetch_sources_filters_by_topic_and_dedupes(self) -> None:
        state = {
            "topic": "retrieval augmented generation",
            "research_questions": ["How does RAG improve retrieval quality?"],
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
                {"uid": "p-off", "title": "Hanabi strategy", "abstract": "game agents"},
            ],
            "web_sources": [
                {"uid": "w-new", "title": "RAG in production", "snippet": "retrieval and generation"},
                {"uid": "w-old", "title": "duplicate web", "snippet": "retrieval"},
                {"uid": "w-off", "title": "football news", "snippet": "sports"},
            ],
        }
        with patch(
            "src.agent.nodes.dispatch",
            return_value=TaskResult(success=True, data=provider_result),
        ) as dispatch_mock:
            out = nodes.fetch_sources(state)

        self.assertEqual([p["uid"] for p in sget(out, "papers", [])], ["p-new"])
        self.assertEqual([w["uid"] for w in sget(out, "web_sources", [])], ["w-new"])
        task = dispatch_mock.call_args.args[0]
        self.assertEqual(task.params["academic_queries"], ["qa"])
        self.assertEqual(task.params["web_queries"], ["qw", "qa", "qb"])

    def test_fetch_sources_returns_failure_status_when_dispatch_fails(self) -> None:
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
            "src.agent.nodes.dispatch",
            return_value=TaskResult(success=False, error="backend down"),
        ):
            out = nodes.fetch_sources(state)

        self.assertEqual(sget(out, "papers", []), [])
        self.assertEqual(sget(out, "web_sources", []), [])
        self.assertIn("Fetch failed: backend down", out["status"])

    def test_evaluate_progress_stops_at_max_iterations(self) -> None:
        state = {"iteration": 2, "max_iterations": 3, "_cfg": {}, "topic": "x"}
        out = nodes.evaluate_progress(state)
        self.assertFalse(out["should_continue"])
        self.assertIn("Max iterations", out["status"])

    def test_evaluate_progress_stops_when_budget_exceeded(self) -> None:
        state = {
            "iteration": 0,
            "max_iterations": 3,
            "_cfg": {"_budget_guard": self._Guard()},
            "topic": "x",
            "papers": [{"uid": "p1"}],
            "web_sources": [],
        }
        out = nodes.evaluate_progress(state)
        self.assertFalse(out["should_continue"])
        self.assertIn("Budget exceeded", out["status"])

    def test_evaluate_progress_stops_when_no_sources(self) -> None:
        state = {"iteration": 0, "max_iterations": 3, "_cfg": {}, "topic": "x", "papers": [], "web_sources": []}
        out = nodes.evaluate_progress(state)
        self.assertFalse(out["should_continue"])
        self.assertIn("No sources found", out["status"])

    def test_evaluate_progress_forces_continue_on_unresolved_audit_gaps(self) -> None:
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
        with patch("src.agent.nodes._llm_call", return_value='{"should_continue": false, "gaps": []}'):
            out = nodes.evaluate_progress(state)

        self.assertTrue(out["should_continue"])
        self.assertTrue(any("Evidence gap in RQ: rq1" in g for g in sget(out, "gaps", [])))


if __name__ == "__main__":
    unittest.main()
