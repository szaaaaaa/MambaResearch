from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src.agent.core.executor import TaskRequest, TaskResult
from src.agent.core.executor_router import register_executor
from src.agent.infra.indexing.chroma_indexing import (
    build_web_index,
    chunk_text,
    index_pdf_documents,
    init_run_tracking,
    upsert_run_doc_records,
    upsert_run_session_record,
)


class IndexExecutor:
    def supported_actions(self) -> List[str]:
        return [
            "init_run_tracking",
            "upsert_run_session_record",
            "index_pdf_documents",
            "chunk_text",
            "build_web_index",
            "upsert_run_doc_records",
        ]

    def execute(self, task: TaskRequest, cfg: Dict[str, Any]) -> TaskResult:
        try:
            action = task.action
            params = task.params

            if action == "init_run_tracking":
                init_run_tracking(str(params["sqlite_path"]))
                return TaskResult(success=True, data={"ok": True})

            if action == "upsert_run_session_record":
                upsert_run_session_record(
                    str(params["sqlite_path"]),
                    run_id=str(params["run_id"]),
                    topic=str(params.get("topic", "")),
                )
                return TaskResult(success=True, data={"ok": True})

            if action == "index_pdf_documents":
                pdf_paths = [Path(p) for p in params.get("pdfs", [])]
                retrieval_cfg = cfg.get("retrieval", {})
                result = index_pdf_documents(
                    persist_dir=str(params["persist_dir"]),
                    collection_name=str(params["collection_name"]),
                    pdfs=pdf_paths,
                    chunk_size=int(params["chunk_size"]),
                    overlap=int(params["overlap"]),
                    run_id=str(params.get("run_id", "")),
                    embedding_model=str(retrieval_cfg.get("embedding_model", "all-MiniLM-L6-v2")),
                    build_bm25=bool(retrieval_cfg.get("hybrid", False)),
                    root=Path(str(cfg.get("_root", "."))),
                    cfg=cfg,
                )
                return TaskResult(success=True, data=dict(result))

            if action == "chunk_text":
                chunks = chunk_text(
                    str(params.get("text", "")),
                    chunk_size=int(params["chunk_size"]),
                    overlap=int(params["overlap"]),
                )
                return TaskResult(success=True, data={"chunks": list(chunks)})

            if action == "build_web_index":
                retrieval_cfg = cfg.get("retrieval", {})
                build_web_index(
                    persist_dir=str(params["persist_dir"]),
                    collection_name=str(params["collection_name"]),
                    chunks=list(params.get("chunks", [])),
                    doc_id=str(params["doc_id"]),
                    run_id=str(params.get("run_id", "")),
                    embedding_model=str(retrieval_cfg.get("embedding_model", "all-MiniLM-L6-v2")),
                    build_bm25=bool(retrieval_cfg.get("hybrid", False)),
                )
                return TaskResult(success=True, data={"ok": True})

            if action == "upsert_run_doc_records":
                upsert_run_doc_records(
                    str(params["sqlite_path"]),
                    run_id=str(params["run_id"]),
                    doc_uids=list(params.get("doc_uids", [])),
                    doc_type=str(params["doc_type"]),
                )
                return TaskResult(success=True, data={"ok": True})

            return TaskResult(success=False, error=f"Unsupported action '{action}'")
        except Exception as exc:
            return TaskResult(success=False, error=str(exc))


register_executor(IndexExecutor())
