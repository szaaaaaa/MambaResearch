from __future__ import annotations

import unittest

from src.agent.core.evidence import _build_claim_evidence_map


class CoreEvidenceTest(unittest.TestCase):
    def test_build_claim_evidence_map_avoids_duplicate_claims(self) -> None:
        analyses = [
            {
                "uid": "arxiv:1",
                "title": "Paper A",
                "summary": "Agentic RAG differs from traditional RAG through adaptive retrieval.",
                "key_findings": ["Agentic RAG differs from traditional RAG through adaptive retrieval."],
                "relevance_score": 0.9,
                "limitations": [],
                "source": "arxiv",
            },
            {
                "uid": "arxiv:2",
                "title": "Paper B",
                "summary": "Agentic RAG differs from traditional RAG through adaptive retrieval.",
                "key_findings": ["Agentic RAG differs from traditional RAG through adaptive retrieval."],
                "relevance_score": 0.8,
                "limitations": [],
                "source": "arxiv",
            },
        ]
        out = _build_claim_evidence_map(
            research_questions=[
                "What are architecture differences in agentic RAG?",
                "How should we evaluate trajectories in agentic RAG?",
            ],
            analyses=analyses,
            core_min_a_ratio=0.7,
        )
        claims = [x["claim"] for x in out]
        self.assertEqual(len(claims), 2)
        self.assertEqual(len(set(claims)), 2)

    def test_build_claim_evidence_map_enforces_min_per_rq_with_arxiv_fallback(self) -> None:
        analyses = [
            {
                "uid": "arxiv:1",
                "title": "Paper A",
                "summary": "Prototype replay improves drift recovery.",
                "key_findings": ["Prototype replay improves drift recovery."],
                "relevance_score": 0.9,
                "limitations": [],
                "source": "arxiv",
            },
            {
                "uid": "arxiv:2",
                "title": "Paper B",
                "summary": "Embedding clustering stabilizes replay sampling.",
                "key_findings": ["Embedding clustering stabilizes replay sampling."],
                "relevance_score": 0.85,
                "limitations": [],
                "source": "arxiv",
            },
        ]
        out = _build_claim_evidence_map(
            research_questions=["How to prioritize replay under concept drift?"],
            analyses=analyses,
            core_min_a_ratio=0.7,
            min_evidence_per_rq=2,
            allow_graceful_degrade=True,
        )
        self.assertEqual(len(out), 1)
        self.assertGreaterEqual(len(out[0]["evidence"]), 2)

    def test_build_claim_evidence_map_graceful_degrade_marks_caveat(self) -> None:
        analyses = [
            {
                "uid": "arxiv:1",
                "title": "Paper A",
                "summary": "Prototype replay improves drift recovery.",
                "key_findings": ["Prototype replay improves drift recovery."],
                "relevance_score": 0.9,
                "limitations": [],
                "source": "arxiv",
            }
        ]
        out = _build_claim_evidence_map(
            research_questions=["How to prioritize replay under concept drift?"],
            analyses=analyses,
            core_min_a_ratio=0.7,
            min_evidence_per_rq=2,
            allow_graceful_degrade=True,
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]["evidence"]), 1)
        self.assertIn("Evidence below minimum (1/2)", out[0].get("caveat", ""))

    def test_build_claim_evidence_map_aligns_claim_with_rq_tokens(self) -> None:
        analyses = [
            {
                "uid": "arxiv:1",
                "title": "Paper A",
                "summary": "PMR mitigates catastrophic forgetting with prototype replay.",
                "key_findings": ["PMR mitigates catastrophic forgetting with prototype replay."],
                "relevance_score": 0.9,
                "limitations": [],
                "source": "arxiv",
            },
            {
                "uid": "arxiv:2",
                "title": "Paper B",
                "summary": "Prototype replay improves robustness.",
                "key_findings": ["Prototype replay improves robustness."],
                "relevance_score": 0.8,
                "limitations": [],
                "source": "arxiv",
            },
        ]
        rq = "How does low-bit quantization of latent embeddings affect precision of prototype selection?"
        out = _build_claim_evidence_map(
            research_questions=[rq],
            analyses=analyses,
            core_min_a_ratio=0.7,
            min_evidence_per_rq=2,
            allow_graceful_degrade=True,
            align_claim_to_rq=True,
            min_claim_rq_relevance=0.2,
            claim_anchor_terms_max=4,
        )
        claim = out[0]["claim"].lower()
        self.assertTrue(claim.startswith("regarding "))
        self.assertIn("quantization", claim)
        self.assertIn("latent", claim)


if __name__ == "__main__":
    unittest.main()
