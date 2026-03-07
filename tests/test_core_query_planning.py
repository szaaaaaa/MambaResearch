from __future__ import annotations

import unittest

from src.agent.core.query_planning import (
    _default_sections_for_intent,
    _expand_query_set,
    _infer_intent,
    _load_budget_and_scope,
    _route_query,
)


class CoreQueryPlanningTest(unittest.TestCase):
    def test_infer_intent_and_default_sections(self) -> None:
        self.assertEqual(_infer_intent("A vs B"), "comparison")
        self.assertEqual(_infer_intent("RAG migration roadmap"), "roadmap")
        self.assertEqual(_infer_intent("Plain topic"), "survey")
        self.assertEqual(len(_default_sections_for_intent("comparison")), 5)
        self.assertEqual(len(_default_sections_for_intent("roadmap")), 5)
        self.assertEqual(len(_default_sections_for_intent("other")), 5)

    def test_load_budget_and_scope(self) -> None:
        state = {"topic": "x", "scope": {"intent": "custom"}, "budget": {"max_sections": 2}}
        cfg = {"agent": {"budget": {"max_sections": 9}}}
        scope, budget = _load_budget_and_scope(state, cfg)
        self.assertEqual(scope, {"intent": "custom"})
        self.assertEqual(budget, {"max_sections": 2})

        state = {"topic": "A vs B in RAG"}
        cfg = {"agent": {"budget": {"max_research_questions": 2, "max_sections": 2, "max_references": 8}}}
        scope, budget = _load_budget_and_scope(state, cfg)
        self.assertEqual(scope["intent"], "comparison")
        self.assertEqual(len(scope["allowed_sections"]), 2)
        self.assertEqual(budget["max_research_questions"], 2)
        self.assertEqual(budget["max_sections"], 2)
        self.assertEqual(budget["max_references"], 8)

        namespaced_state = {"planning": {"scope": {"intent": "custom"}, "budget": {"max_sections": 1}}}
        scope, budget = _load_budget_and_scope(namespaced_state, {"agent": {"budget": {"max_sections": 9}}})
        self.assertEqual(scope, {"intent": "custom"})
        self.assertEqual(budget, {"max_sections": 1})

    def test_route_query_for_simple_and_deep_cases(self) -> None:
        simple = _route_query("what is retrieval augmented generation", {"agent": {}})
        self.assertTrue(simple["simple"])
        self.assertTrue(simple["use_web"])
        self.assertFalse(simple["use_academic"])
        self.assertFalse(simple["download_pdf"])

        deep = _route_query("rag benchmark latency tradeoff", {"agent": {}})
        self.assertFalse(deep["simple"])
        self.assertTrue(deep["use_web"])
        self.assertTrue(deep["use_academic"])
        self.assertTrue(deep["download_pdf"])

        simple_override = _route_query(
            "what is retrieval augmented generation",
            {"agent": {"dynamic_retrieval": {"simple_query_academic": True, "simple_query_pdf": True}}},
        )
        self.assertTrue(simple_override["use_academic"])
        self.assertTrue(simple_override["download_pdf"])

    def test_route_query_uses_configurable_terms(self) -> None:
        cfg = {"agent": {"dynamic_retrieval": {"simple_query_terms": ["plain"], "deep_query_terms": ["hardcore"]}}}
        out_simple = _route_query("plain overview", cfg)
        out_deep = _route_query("plain hardcore benchmark", cfg)
        self.assertTrue(out_simple["simple"])
        self.assertFalse(out_deep["simple"])

    def test_expand_query_set_dedupes_and_limits(self) -> None:
        out = _expand_query_set(
            topic="RAG",
            rq_list=["How to evaluate RAG systems?"],
            seed_queries=["RAG", "rag"],
            max_per_rq=3,
            max_total=4,
        )
        self.assertLessEqual(len(out), 4)
        self.assertEqual(out[0]["query"], "RAG")
        self.assertEqual(len({item["query"].lower() for item in out}), len(out))


if __name__ == "__main__":
    unittest.main()
