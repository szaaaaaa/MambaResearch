"""Tests for S1 state accumulation at the stage layer."""
from __future__ import annotations

import json
import unittest

from src.agent.core.executor import TaskResult
from src.agent.stages.analysis import analyze_sources
from src.agent.stages.indexing import index_sources
from src.agent.stages.retrieval import fetch_sources


class FetchSourcesCumulativeTest(unittest.TestCase):
    def _base_state(self):
        return {
            "topic": "RAG",
            "papers": [
                {"uid": "existing-1", "title": "Old Paper", "authors": [], "source": "arxiv"},
            ],
            "web_sources": [
                {"uid": "existing-web-1", "title": "Old Web", "source": "web"},
            ],
            "search_queries": ["RAG survey"],
            "_cfg": {
                "agent": {},
                "sources": {"arxiv": {"enabled": True}, "web": {"enabled": True}},
            },
        }

    def test_no_new_results_preserves_existing(self):
        state = self._base_state()
        result = fetch_sources(
            state,
            state_view=lambda x: x,
            get_cfg=lambda x: x.get("_cfg", {}),
            ns=lambda x: x,
            dispatch=lambda task, cfg: TaskResult(success=True, data={"papers": [], "web_sources": []}),
            build_topic_keywords=lambda state, cfg: {"rag"},
            build_topic_anchor_terms=lambda state, cfg: set(),
            is_topic_relevant=lambda **kwargs: True,
        )
        papers = result.get("papers", [])
        web = result.get("web_sources", [])
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["uid"], "existing-1")
        self.assertEqual(len(web), 1)
        self.assertEqual(web[0]["uid"], "existing-web-1")

    def test_new_results_merge_with_existing(self):
        state = self._base_state()
        result = fetch_sources(
            state,
            state_view=lambda x: x,
            get_cfg=lambda x: x.get("_cfg", {}),
            ns=lambda x: x,
            dispatch=lambda task, cfg: TaskResult(
                success=True,
                data={
                    "papers": [
                        {"uid": "new-1", "title": "New Paper", "authors": [], "abstract": "RAG stuff", "source": "arxiv"},
                    ],
                    "web_sources": [],
                },
            ),
            build_topic_keywords=lambda state, cfg: {"rag"},
            build_topic_anchor_terms=lambda state, cfg: set(),
            is_topic_relevant=lambda **kwargs: True,
        )
        papers = result.get("papers", [])
        self.assertEqual(len(papers), 2)
        uids = {p["uid"] for p in papers}
        self.assertIn("existing-1", uids)
        self.assertIn("new-1", uids)

    def test_fetch_failure_preserves_existing(self):
        state = self._base_state()
        result = fetch_sources(
            state,
            state_view=lambda x: x,
            get_cfg=lambda x: x.get("_cfg", {}),
            ns=lambda x: x,
            dispatch=lambda task, cfg: TaskResult(success=False, error="timeout"),
            build_topic_keywords=lambda state, cfg: {"rag"},
            build_topic_anchor_terms=lambda state, cfg: set(),
            is_topic_relevant=lambda **kwargs: True,
        )
        papers = result.get("papers", [])
        self.assertEqual(len(papers), 1)


class AnalyzeSourcesCumulativeTest(unittest.TestCase):
    def test_no_new_analyses_preserves_existing(self):
        existing_analysis = {
            "uid": "old-1",
            "title": "Existing",
            "summary": "old",
            "key_findings": ["old finding"],
            "source": "arxiv",
        }
        state = {
            "topic": "RAG",
            "papers": [],
            "web_sources": [],
            "analyses": [existing_analysis],
            "findings": ["old finding"],
            "_cfg": {"agent": {}, "llm": {"model": "gpt-4.1-mini"}, "index": {}},
        }
        result = analyze_sources(
            state,
            state_view=lambda x: x,
            get_cfg=lambda x: x.get("_cfg", {}),
            ns=lambda x: x,
            dispatch=lambda task, cfg: TaskResult(success=False, error="unused"),
            llm_call=lambda *args, **kwargs: json.dumps({}),
            parse_json=json.loads,
            extract_table_signals=lambda text: [],
            source_tier=lambda analysis: "A",
        )
        analyses = result.get("analyses", [])
        findings = result.get("findings", [])
        self.assertEqual(len(analyses), 1)
        self.assertEqual(analyses[0]["uid"], "old-1")
        self.assertEqual(len(findings), 1)


class IndexSourcesCumulativeTest(unittest.TestCase):
    def test_no_new_indexes_preserves_existing_ids(self):
        state = {
            "topic": "RAG",
            "papers": [],
            "web_sources": [],
            "indexed_paper_ids": ["old-paper-id"],
            "indexed_web_ids": ["old-web-id"],
            "_cfg": {
                "_root": ".",
                "_run_id": "",
                "index": {},
                "metadata_store": {},
            },
        }
        result = index_sources(
            state,
            state_view=lambda x: x,
            get_cfg=lambda x: x.get("_cfg", {}),
            ns=lambda x: x,
            dispatch=lambda task, cfg: TaskResult(success=True, data={}),
        )
        paper_ids = result.get("indexed_paper_ids", [])
        web_ids = result.get("indexed_web_ids", [])
        self.assertIn("old-paper-id", paper_ids)
        self.assertIn("old-web-id", web_ids)


if __name__ == "__main__":
    unittest.main()
