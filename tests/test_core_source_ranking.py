from __future__ import annotations

import unittest

from src.agent.core.source_ranking import (
    _dedupe_and_rank_analyses,
    _is_topic_relevant,
    _uid_to_resolvable_url,
)


class CoreSourceRankingTest(unittest.TestCase):
    def test_is_topic_relevant_with_block_terms(self) -> None:
        kws = {"rag", "retrieval", "generation"}
        self.assertTrue(
            _is_topic_relevant(
                text="A retrieval augmented generation tutorial",
                topic_keywords=kws,
                block_terms=[],
                min_hits=2,
            )
        )
        self.assertFalse(
            _is_topic_relevant(
                text="Hanabi benchmark and game agents",
                topic_keywords=kws,
                block_terms=["hanabi"],
                min_hits=1,
            )
        )

    def test_is_topic_relevant_with_anchor_terms(self) -> None:
        kws = {"concept", "drift", "forecasting"}
        anchors = {"prototype", "replay"}
        self.assertFalse(
            _is_topic_relevant(
                text="Concept drift methods for forecasting",
                topic_keywords=kws,
                block_terms=[],
                min_hits=1,
                anchor_terms=anchors,
                min_anchor_hits=1,
            )
        )
        self.assertTrue(
            _is_topic_relevant(
                text="Prototype replay for concept drift forecasting",
                topic_keywords=kws,
                block_terms=[],
                min_hits=1,
                anchor_terms=anchors,
                min_anchor_hits=1,
            )
        )

    def test_uid_to_resolvable_url(self) -> None:
        self.assertEqual(
            _uid_to_resolvable_url("arxiv:2401.12345"),
            "https://arxiv.org/abs/2401.12345",
        )
        self.assertEqual(
            _uid_to_resolvable_url("doi:10.1000/xyz"),
            "https://doi.org/10.1000/xyz",
        )
        self.assertEqual(_uid_to_resolvable_url("x"), "")

    def test_dedupe_and_rank_analyses(self) -> None:
        analyses = [
            {"uid": "arxiv:1", "title": "Old", "relevance_score": 0.1, "source": "arxiv"},
            {"uid": "arxiv:1", "title": "New", "relevance_score": 0.9, "source": "arxiv"},
            {"uid": "doi:10.1/x", "title": "DOI", "relevance_score": 0.8, "source": "web", "url": ""},
            {"title": "Web", "url": "https://example.com/path/", "relevance_score": 0.7, "source": "web"},
        ]
        out = _dedupe_and_rank_analyses(analyses, max_items=10)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]["title"], "New")
        doi_item = next(x for x in out if x.get("uid") == "doi:10.1/x")
        self.assertEqual(doi_item["url"], "https://doi.org/10.1/x")


if __name__ == "__main__":
    unittest.main()
