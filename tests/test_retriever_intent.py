from __future__ import annotations

import unittest

from src.rag.retriever import (
    _apply_intent_prior,
    _collapse_figure_duplicates,
    _detect_query_intent,
    _ensure_figure_presence,
)


class RetrieverIntentTest(unittest.TestCase):
    def test_detect_query_intent_covers_visual_and_formula_queries(self) -> None:
        self.assertEqual(_detect_query_intent("attention architecture diagram"), "visual")
        self.assertEqual(_detect_query_intent("请解释这个架构图"), "visual")
        self.assertEqual(_detect_query_intent("scaled dot product attention equation"), "formula")
        self.assertEqual(_detect_query_intent("transformer training details"), "general")

    def test_apply_intent_prior_boosts_figure_chunk_for_visual_query(self) -> None:
        hits = [
            {"id": "t1", "text": "plain text", "meta": {"chunk_type": "text"}, "rrf_score": 0.100},
            {"id": "f1", "text": "[Figure] architecture", "meta": {"chunk_type": "figure"}, "rrf_score": 0.099},
        ]

        boosted = _apply_intent_prior(hits, "visual")

        self.assertEqual(boosted[0]["id"], "f1")

    def test_collapse_figure_duplicates_keeps_single_best_figure(self) -> None:
        hits = [
            {"id": "f1a", "text": "figure a", "meta": {"chunk_type": "figure", "figure_id": "fig:1"}, "reranker_score": 0.9},
            {"id": "f1b", "text": "figure b", "meta": {"chunk_type": "figure", "figure_id": "fig:1"}, "reranker_score": 0.8},
            {"id": "t1", "text": "text", "meta": {"chunk_type": "text"}, "reranker_score": 0.7},
        ]

        collapsed = _collapse_figure_duplicates(hits)

        self.assertEqual([hit["id"] for hit in collapsed], ["f1a", "t1"])

    def test_ensure_figure_presence_promotes_best_figure_into_top_k(self) -> None:
        hits = [
            {"id": "t1", "text": "text1", "meta": {"chunk_type": "text"}, "reranker_score": 0.95},
            {"id": "t2", "text": "text2", "meta": {"chunk_type": "text"}, "reranker_score": 0.90},
            {"id": "f1", "text": "figure1", "meta": {"chunk_type": "figure", "figure_id": "fig:1"}, "reranker_score": 0.85},
            {"id": "f2", "text": "figure2", "meta": {"chunk_type": "figure", "figure_id": "fig:2"}, "reranker_score": 0.80},
        ]

        adjusted = _ensure_figure_presence(hits, top_k=2, min_figure_slots=1)

        top_ids = [hit["id"] for hit in adjusted[:2]]
        self.assertIn("f1", top_ids)


if __name__ == "__main__":
    unittest.main()
