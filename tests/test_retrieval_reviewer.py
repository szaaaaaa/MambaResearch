"""Tests for the retrieval reviewer gate."""
from __future__ import annotations

import unittest

from src.agent.reviewers.retrieval_reviewer import review_retrieval


def _make_state(
    *,
    papers=None,
    web_sources=None,
    analyses=None,
    research_questions=None,
    search_queries=None,
    cfg=None,
):
    return {
        "topic": "concept drift detection",
        "planning": {
            "research_questions": research_questions or [],
            "search_queries": search_queries or [],
            "scope": {},
            "budget": {},
            "query_routes": {},
            "_academic_queries": search_queries or [],
            "_web_queries": search_queries or [],
        },
        "research": {
            "papers": papers or [],
            "web_sources": web_sources or [],
            "analyses": analyses or [],
            "findings": [],
            "synthesis": "",
            "indexed_paper_ids": [],
            "indexed_web_ids": [],
            "memory_summary": "",
            "experiment_plan": {},
            "experiment_results": {},
        },
        "evidence": {
            "gaps": [],
            "claim_evidence_map": [],
            "evidence_audit_log": [],
        },
        "review": {
            "retrieval_review": {},
            "citation_validation": {},
            "experiment_review": {},
            "claim_verdicts": [],
            "reviewer_log": [],
        },
        "report": {
            "report": "",
            "report_critic": {},
            "repair_attempted": False,
            "acceptance_metrics": {},
        },
        "iteration": 0,
        "max_iterations": 3,
        "should_continue": False,
        "_cfg": cfg or {},
        "_retrieval_review_retries": 0,
    }


def _paper(uid, title="Test Paper", year=2024, source="arxiv", venue=""):
    return {
        "uid": uid,
        "title": title,
        "year": year,
        "source": source,
        "venue": venue,
        "url": f"https://arxiv.org/abs/{uid}" if source == "arxiv" else "",
        "abstract": title,
    }


def _analysis(uid, title="Test Analysis", source="arxiv", relevance=0.8, venue=""):
    return {
        "uid": uid,
        "title": title,
        "source": source,
        "url": f"https://arxiv.org/abs/{uid}" if source == "arxiv" else "",
        "relevance_score": relevance,
        "summary": title,
        "key_findings": [title],
        "venue": venue,
    }


class TestRetrievalReviewerPass(unittest.TestCase):
    def test_sufficient_diverse_sources_pass(self):
        papers = [
            _paper(f"arxiv:{i}", f"Paper about concept drift {i}", 2020 + i, venue=f"Venue{i}")
            for i in range(6)
        ]
        analyses = [
            _analysis(f"arxiv:{i}", f"Analysis about concept drift {i}", venue=f"Venue{i}")
            for i in range(6)
        ]
        state = _make_state(
            papers=papers,
            analyses=analyses,
            research_questions=["How does concept drift affect model performance?"],
            search_queries=["concept drift detection"],
        )
        result = review_retrieval(state)
        review = result.get("review", {}).get("retrieval_review", {})
        self.assertEqual(review["verdict"]["status"], "pass")
        self.assertEqual(review["verdict"]["action"], "continue")


class TestRetrievalReviewerWarn(unittest.TestCase):
    def test_low_source_count_warns(self):
        papers = [_paper("arxiv:1", "Concept drift paper", 2024)]
        analyses = [_analysis("arxiv:1", "Concept drift analysis")]
        state = _make_state(
            papers=papers,
            analyses=analyses,
            research_questions=["How does concept drift affect models?"],
            search_queries=["concept drift"],
        )
        result = review_retrieval(state)
        review = result.get("review", {}).get("retrieval_review", {})
        self.assertIn(review["verdict"]["status"], ("warn", "fail"))
        self.assertGreater(len(review["verdict"]["issues"]), 0)


class TestRetrievalReviewerFail(unittest.TestCase):
    def test_empty_sources_fail(self):
        state = _make_state(
            papers=[],
            web_sources=[],
            analyses=[],
            research_questions=[
                "How does concept drift affect models?",
                "What are the best drift detectors?",
            ],
            search_queries=["concept drift"],
        )
        result = review_retrieval(state)
        review = result.get("review", {}).get("retrieval_review", {})
        self.assertEqual(review["verdict"]["status"], "fail")
        self.assertEqual(review["verdict"]["action"], "retry_upstream")
        self.assertGreater(len(review["suggested_queries"]), 0)

    def test_retry_injects_queries(self):
        state = _make_state(
            papers=[],
            analyses=[],
            research_questions=["How does concept drift affect neural networks?"],
            search_queries=["concept drift"],
        )
        result = review_retrieval(state)
        # Should have supplemental queries in state update
        if "search_queries" in result:
            self.assertGreater(len(result["search_queries"]), 1)


class TestRQCoverage(unittest.TestCase):
    def test_uncovered_rq_detected(self):
        papers = [
            _paper(f"arxiv:{i}", f"Paper about reinforcement learning {i}", 2020 + i, venue=f"V{i}")
            for i in range(6)
        ]
        analyses = [
            _analysis(f"arxiv:{i}", f"Analysis about reinforcement learning {i}", venue=f"V{i}")
            for i in range(6)
        ]
        state = _make_state(
            papers=papers,
            analyses=analyses,
            research_questions=[
                "What is the impact of quantum computing on cryptography?",
            ],
            search_queries=["reinforcement learning"],
        )
        result = review_retrieval(state)
        review = result.get("review", {}).get("retrieval_review", {})
        self.assertGreater(len(review["missing_key_topics"]), 0)


class TestDiversityStats(unittest.TestCase):
    def test_stats_computed(self):
        papers = [
            _paper("arxiv:1", "Paper A", 2022, venue="NeurIPS"),
            _paper("arxiv:2", "Paper B", 2024, venue="ICML"),
        ]
        state = _make_state(papers=papers)
        result = review_retrieval(state)
        review = result.get("review", {}).get("retrieval_review", {})
        stats = review["diversity_stats"]
        self.assertEqual(stats["total_sources"], 2)
        self.assertEqual(stats["academic_count"], 2)
        self.assertIn("NeurIPS", stats["unique_venues"])
        self.assertIn("ICML", stats["unique_venues"])
        self.assertIn("semantic_purity_ratio", stats)
        self.assertGreaterEqual(stats["semantic_purity_ratio"], 0.0)


class TestSemanticPurity(unittest.TestCase):
    def test_off_topic_analyses_raise_reject_ratio_issue(self):
        papers = [
            _paper(f"arxiv:{i}", f"Paper about reinforcement learning {i}", 2020 + i, venue=f"V{i}")
            for i in range(6)
        ]
        analyses = [
            _analysis(f"arxiv:{i}", f"Analysis about reinforcement learning {i}", venue=f"V{i}")
            for i in range(6)
        ]
        state = _make_state(
            papers=papers,
            analyses=analyses,
            research_questions=["How does concept drift affect model performance?"],
            search_queries=["reinforcement learning"],
        )
        result = review_retrieval(state)
        review = result.get("review", {}).get("retrieval_review", {})
        stats = review["diversity_stats"]
        self.assertGreaterEqual(stats["reject_ratio"], 0.8)
        self.assertTrue(any("Reject ratio" in issue for issue in review["verdict"]["issues"]))


if __name__ == "__main__":
    unittest.main()
