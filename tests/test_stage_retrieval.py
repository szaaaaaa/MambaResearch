from __future__ import annotations

import unittest

from src.agent.core.executor import TaskResult
from src.agent.stages.retrieval import fetch_sources


class StageRetrievalTest(unittest.TestCase):
    def test_fetch_sources_filters_and_dedupes(self) -> None:
        state = {
            "topic": "retrieval augmented generation",
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
        seen: list[object] = []

        def dispatch(task, cfg):
            seen.append(task)
            return TaskResult(success=True, data=provider_result)

        def is_topic_relevant(**kwargs) -> bool:
            text = kwargs["text"].lower()
            return "retrieval" in text or "generation" in text

        out = fetch_sources(
            state,
            state_view=lambda x: x,
            get_cfg=lambda x: x.get("_cfg", {}),
            ns=lambda x: x,
            dispatch=dispatch,
            build_topic_keywords=lambda state, cfg: {"retrieval", "generation"},
            build_topic_anchor_terms=lambda state, cfg: set(),
            is_topic_relevant=is_topic_relevant,
        )

        self.assertEqual([paper["uid"] for paper in out["papers"]], ["p-old", "p-new"])
        self.assertEqual([web["uid"] for web in out["web_sources"]], ["w-old", "w-new"])
        self.assertEqual(seen[0].params["academic_queries"], ["qa"])
        self.assertEqual(seen[0].params["web_queries"], ["qw", "qa", "qb"])

    def test_fetch_sources_preserves_existing_on_failure(self) -> None:
        state = {
            "topic": "rag retrieval",
            "_academic_queries": ["qa"],
            "_web_queries": ["qw"],
            "query_routes": {},
            "papers": [{"uid": "p-old"}],
            "web_sources": [{"uid": "w-old"}],
            "_cfg": {},
        }

        out = fetch_sources(
            state,
            state_view=lambda x: x,
            get_cfg=lambda x: x.get("_cfg", {}),
            ns=lambda x: x,
            dispatch=lambda task, cfg: TaskResult(success=False, error="backend down"),
            build_topic_keywords=lambda state, cfg: {"rag"},
            build_topic_anchor_terms=lambda state, cfg: set(),
            is_topic_relevant=lambda **kwargs: True,
        )

        self.assertEqual(out["papers"], [{"uid": "p-old"}])
        self.assertEqual(out["web_sources"], [{"uid": "w-old"}])
        self.assertIn("Fetch failed: backend down", out["status"])


if __name__ == "__main__":
    unittest.main()
