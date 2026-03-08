from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src.agent.core.executor import TaskRequest, TaskResult
from src.agent.core.executor_router import register_executor
from src.common.rag_config import index_backend, retrieval_effective_embedding_model, retrieval_embedding_backend


def _resolve_indexing_backend(cfg: Dict[str, Any]):
    backend = index_backend(cfg)
    if backend == "faiss":
        from src.agent.infra.indexing import faiss_indexing as backend_module
        return backend_module
    from src.agent.infra.indexing import chroma_indexing as backend_module
    return backend_module


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
            backend_module = _resolve_indexing_backend(cfg)

            if action == "init_run_tracking":
                backend_module.init_run_tracking(str(params["sqlite_path"]))
                return TaskResult(success=True, data={"ok": True})

            if action == "upsert_run_session_record":
                backend_module.upsert_run_session_record(
                    str(params["sqlite_path"]),
                    run_id=str(params["run_id"]),
                    topic=str(params.get("topic", "")),
                )
                return TaskResult(success=True, data={"ok": True})

            if action == "index_pdf_documents":
                pdf_paths = [Path(p) for p in params.get("pdfs", [])]
                retrieval_cfg = cfg.get("retrieval", {})
                result = backend_module.index_pdf_documents(
                    persist_dir=str(params["persist_dir"]),
                    collection_name=str(params["collection_name"]),
                    pdfs=pdf_paths,
                    chunk_size=int(params["chunk_size"]),
                    overlap=int(params["overlap"]),
                    run_id=str(params.get("run_id", "")),
                    embedding_model=retrieval_effective_embedding_model(
                        cfg,
                        str(retrieval_cfg.get("embedding_model", "all-MiniLM-L6-v2")),
                    ),
                    embedding_backend=retrieval_embedding_backend(cfg),
                    build_bm25=bool(retrieval_cfg.get("hybrid", False)),
                    root=Path(str(cfg.get("_root", "."))),
                    cfg=cfg,
                    ingest_overrides=dict(params.get("ingest_overrides", {}) or {}),
                    allow_existing_doc_updates=bool(params.get("allow_existing_doc_updates", False)),
                    include_text_chunks=bool(params.get("include_text_chunks", True)),
                )
                return TaskResult(success=True, data=dict(result))

            if action == "chunk_text":
                chunks = backend_module.chunk_text(
                    str(params.get("text", "")),
                    chunk_size=int(params["chunk_size"]),
                    overlap=int(params["overlap"]),
                )
                return TaskResult(success=True, data={"chunks": list(chunks)})

            if action == "build_web_index":
                retrieval_cfg = cfg.get("retrieval", {})
                backend_module.build_web_index(
                    persist_dir=str(params["persist_dir"]),
                    collection_name=str(params["collection_name"]),
                    chunks=list(params.get("chunks", [])),
                    doc_id=str(params["doc_id"]),
                    run_id=str(params.get("run_id", "")),
                    embedding_model=retrieval_effective_embedding_model(
                        cfg,
                        str(retrieval_cfg.get("embedding_model", "all-MiniLM-L6-v2")),
                    ),
                    embedding_backend=retrieval_embedding_backend(cfg),
                    build_bm25=bool(retrieval_cfg.get("hybrid", False)),
                    cfg=cfg,
                )
                return TaskResult(success=True, data={"ok": True})

            if action == "upsert_run_doc_records":
                backend_module.upsert_run_doc_records(
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
