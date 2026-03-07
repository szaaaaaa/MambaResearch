from __future__ import annotations

import json
import unittest

from src.agent.core.executor import TaskResult
from src.agent.stages.analysis import analyze_sources


class StageAnalysisTest(unittest.TestCase):
    def test_analyze_sources_accumulates_analyses_and_findings(self) -> None:
        state = {
            "topic": "retrieval augmented generation",
            "papers": [
                {
                    "uid": "paper-1",
                    "title": "Paper One",
                    "authors": ["Alice"],
                    "abstract": "retrieval quality",
                    "pdf_path": "paper-1.pdf",
                    "source": "arxiv",
                }
            ],
            "web_sources": [
                {
                    "uid": "web-1",
                    "title": "Web One",
                    "url": "https://example.com",
                    "body": "retrieval and generation",
                }
            ],
            "indexed_paper_ids": ["paper-1"],
            "analyses": [{"uid": "old-1", "title": "Old"}],
            "findings": ["old finding"],
            "_cfg": {"agent": {}, "llm": {"model": "gpt-4.1-mini"}, "index": {}, "retrieval": {}},
        }

        def dispatch(task, cfg):
            if task.action == "retrieve_chunks":
                return TaskResult(success=True, data={"hits": [{"text": "retrieval chunk"}]})
            return TaskResult(success=False, error="unexpected")

        llm_payloads = iter(
            [
                json.dumps({"summary": "paper summary", "key_findings": ["paper finding"]}),
                json.dumps({"summary": "web summary", "key_findings": ["web finding"]}),
            ]
        )

        out = analyze_sources(
            state,
            state_view=lambda x: x,
            get_cfg=lambda x: x.get("_cfg", {}),
            ns=lambda x: x,
            dispatch=dispatch,
            llm_call=lambda *args, **kwargs: next(llm_payloads),
            parse_json=json.loads,
            extract_table_signals=lambda text: [],
            source_tier=lambda analysis: "A",
        )

        self.assertEqual(len(out["analyses"]), 3)
        self.assertEqual(out["analyses"][1]["uid"], "paper-1")
        self.assertEqual(out["analyses"][2]["uid"], "web-1")
        self.assertIn("[Paper: Paper One] paper finding", out["findings"])
        self.assertIn("[Web: Web One] web finding", out["findings"])


if __name__ == "__main__":
    unittest.main()
