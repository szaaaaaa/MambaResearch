from __future__ import annotations

import unittest

from src.agent.core.topic_filter import (
    _build_topic_anchor_terms,
    _build_topic_keywords,
    _extract_table_signals,
)


class CoreTopicFilterTest(unittest.TestCase):
    def test_extract_table_signals_finds_table_like_rows(self) -> None:
        text = "\n".join(
            [
                "Summary paragraph",
                "model,acc,f1,latency,seed",
                "baseline,0.80,0.78,120,1",
                "other text",
                "A | B | C",
            ]
        )
        out = _extract_table_signals(text)
        self.assertEqual(len(out), 2)
        self.assertIn("A | B | C", out)
        self.assertIn("baseline,0.80,0.78,120,1", out)

    def test_build_topic_keywords_includes_cfg_terms(self) -> None:
        state = {
            "topic": "Retrieval augmented generation for support bots",
            "research_questions": ["How does retrieval depth affect latency?"],
        }
        cfg = {"agent": {"topic_filter": {"include_terms": ["customer support", "semantic cache"]}}}
        out = _build_topic_keywords(state, cfg)
        self.assertIn("retrieval", out)
        self.assertIn("support", out)
        self.assertIn("customer", out)
        self.assertIn("semantic", out)

    def test_build_topic_anchor_terms_drops_generic_tokens(self) -> None:
        state = {"topic": "Prototype replay for concept drift forecasting"}
        cfg = {"agent": {"topic_filter": {"include_terms": ["time series", "prototype replay"]}}}
        out = _build_topic_anchor_terms(state, cfg)
        self.assertIn("prototype", out)
        self.assertIn("replay", out)
        self.assertIn("forecasting", out)
        self.assertNotIn("concept", out)
        self.assertNotIn("drift", out)


if __name__ == "__main__":
    unittest.main()
