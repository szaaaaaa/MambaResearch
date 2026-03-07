"""Tests for claim extractor reviewer."""
from __future__ import annotations

import unittest

from src.agent.reviewers.claim_extractor import extract_and_assess_claims


def _make_state(*, claim_map=None, analyses=None, report=""):
    return {
        "topic": "concept drift",
        "planning": {"research_questions": [], "search_queries": [], "scope": {},
                      "budget": {}, "query_routes": {}, "_academic_queries": [], "_web_queries": []},
        "research": {"papers": [], "web_sources": [], "analyses": analyses or [],
                      "findings": [], "synthesis": "", "indexed_paper_ids": [],
                      "indexed_web_ids": [], "memory_summary": "",
                      "experiment_plan": {}, "experiment_results": {}},
        "evidence": {"gaps": [], "claim_evidence_map": claim_map or [], "evidence_audit_log": []},
        "review": {"retrieval_review": {}, "citation_validation": {},
                    "experiment_review": {}, "claim_verdicts": [], "reviewer_log": []},
        "report": {"report": report, "report_critic": {}, "repair_attempted": False,
                    "acceptance_metrics": {}},
        "_cfg": {},
    }


class TestClaimExtractor(unittest.TestCase):
    def test_no_claims_warns(self):
        state = _make_state()
        result = extract_and_assess_claims(state)
        review = result.get("review", {})
        self.assertEqual(review["claim_verdicts"], [])
        log = review["reviewer_log"]
        self.assertTrue(any(v["status"] == "warn" for v in log))

    def test_supported_claims(self):
        analyses = [
            {
                "uid": "arxiv:2401.00001",
                "title": "Drift Detection Methods",
                "summary": "Drift detection improves model accuracy significantly",
                "key_findings": ["Drift detection improves model accuracy by 15%"],
                "url": "https://arxiv.org/abs/2401.00001",
            },
            {
                "uid": "arxiv:2401.00002",
                "title": "Improved Drift Detection Accuracy",
                "summary": "Drift detection significantly improves accuracy of deployed models",
                "key_findings": ["Detection accuracy improvement confirmed across datasets"],
                "url": "https://arxiv.org/abs/2401.00002",
            },
        ]
        claim_map = [
            {
                "research_question": "How to detect concept drift?",
                "claim": "Drift detection improves model accuracy significantly",
                "evidence": [
                    {"uid": "arxiv:2401.00001", "url": "https://arxiv.org/abs/2401.00001", "tier": "A"},
                    {"uid": "arxiv:2401.00002", "url": "https://arxiv.org/abs/2401.00002", "tier": "A"},
                ],
                "strength": "A",
            }
        ]
        state = _make_state(claim_map=claim_map, analyses=analyses)
        result = extract_and_assess_claims(state)
        verdicts = result.get("review", {}).get("claim_verdicts", [])
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0]["status"], "supported")

    def test_unsupported_claim_detected(self):
        claim_map = [
            {
                "research_question": "How to detect drift?",
                "claim": "Quantum computing solves drift detection",
                "evidence": [
                    {"uid": "unknown:999", "url": "", "tier": "C"},
                ],
                "strength": "C",
            }
        ]
        state = _make_state(claim_map=claim_map, analyses=[])
        result = extract_and_assess_claims(state)
        verdicts = result.get("review", {}).get("claim_verdicts", [])
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0]["status"], "unsupported")


if __name__ == "__main__":
    unittest.main()
