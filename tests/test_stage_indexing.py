from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from src.agent.core.executor import TaskResult
from src.agent.stages.indexing import index_sources


class StageIndexingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path("tests/.tmp_stage_indexing")
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_preserves_existing_ids_when_nothing_new(self) -> None:
        state = {
            "topic": "RAG",
            "papers": [],
            "web_sources": [],
            "indexed_paper_ids": ["old-paper-id"],
            "indexed_web_ids": ["old-web-id"],
            "_cfg": {"_root": ".", "_run_id": "", "index": {}, "metadata_store": {}},
        }

        out = index_sources(
            state,
            state_view=lambda x: x,
            get_cfg=lambda x: x.get("_cfg", {}),
            ns=lambda x: x,
            dispatch=lambda task, cfg: TaskResult(success=True, data={}),
        )

        self.assertIn("old-paper-id", out["indexed_paper_ids"])
        self.assertIn("old-web-id", out["indexed_web_ids"])

    def test_indexes_new_papers_and_web_sources(self) -> None:
        pdf_path = self.tmp_dir / "paper-a.pdf"
        pdf_path.write_text("pdf", encoding="utf-8")
        state = {
            "topic": "RAG",
            "papers": [{"uid": "paper-a", "pdf_path": str(pdf_path)}],
            "web_sources": [{"uid": "web-a", "body": "x" * 120}],
            "indexed_paper_ids": ["old-paper-id"],
            "indexed_web_ids": ["old-web-id"],
            "_cfg": {
                "_root": ".",
                "_run_id": "run-1",
                "index": {},
                "metadata_store": {},
            },
        }
        actions: list[str] = []

        def dispatch(task, cfg):
            actions.append(task.action)
            if task.action == "index_pdf_documents":
                return TaskResult(success=True, data={"indexed_docs": ["paper-doc"]})
            if task.action == "chunk_text":
                return TaskResult(success=True, data={"chunks": ["chunk-1"]})
            return TaskResult(success=True, data={})

        out = index_sources(
            state,
            state_view=lambda x: x,
            get_cfg=lambda x: x.get("_cfg", {}),
            ns=lambda x: x,
            dispatch=dispatch,
        )

        self.assertEqual(out["indexed_paper_ids"], ["old-paper-id", "paper-doc"])
        self.assertEqual(out["indexed_web_ids"], ["old-web-id", "web-a"])
        self.assertIn("init_run_tracking", actions)
        self.assertIn("index_pdf_documents", actions)
        self.assertIn("build_web_index", actions)


if __name__ == "__main__":
    unittest.main()
