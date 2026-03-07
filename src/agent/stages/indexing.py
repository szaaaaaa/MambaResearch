"""Indexing stage implementation."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List

from src.agent.core.executor import TaskRequest
from src.agent.core.executor_router import dispatch as _default_dispatch
from src.agent.core.schemas import ResearchState
from src.agent.core.state_access import to_namespaced_update, with_flattened_legacy_view

logger = logging.getLogger(__name__)


def index_sources(
    state: ResearchState,
    *,
    state_view: Callable[[ResearchState], Dict[str, Any]] | None = None,
    get_cfg: Callable[[ResearchState], Dict[str, Any]] | None = None,
    ns: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
    dispatch: Callable[..., Any] | None = None,
) -> Dict[str, Any]:
    """Index newly fetched PDFs and web content into separate collections."""
    state_view = state_view or with_flattened_legacy_view
    get_cfg = get_cfg or (lambda current_state: current_state.get("_cfg", {}))
    ns = ns or to_namespaced_update
    dispatch = dispatch or _default_dispatch

    state = state_view(state)
    cfg = get_cfg(state)
    root = Path(cfg.get("_root", "."))
    run_id = cfg.get("_run_id", "")
    persist_dir = str(
        (root / cfg.get("index", {}).get("persist_dir", "data/indexes/chroma")).resolve()
    )
    sqlite_path = str(
        (
            root / cfg.get("metadata_store", {}).get("sqlite_path", "data/metadata/papers.sqlite")
        ).resolve()
    )
    paper_collection = cfg.get("index", {}).get("collection_name", "papers")
    web_collection = cfg.get("index", {}).get("web_collection_name", "web_sources")
    chunk_size = cfg.get("index", {}).get("chunk_size", 1200)
    overlap = cfg.get("index", {}).get("overlap", 200)

    if run_id:
        init_result = dispatch(
            TaskRequest(
                action="init_run_tracking",
                params={"sqlite_path": sqlite_path},
            ),
            cfg,
        )
        if not init_result.success:
            logger.warning("run_tracking init failed: %s", init_result.error)

        session_result = dispatch(
            TaskRequest(
                action="upsert_run_session_record",
                params={
                    "sqlite_path": sqlite_path,
                    "run_id": run_id,
                    "topic": state.get("topic", ""),
                },
            ),
            cfg,
        )
        if not session_result.success:
            logger.warning("run_session upsert failed: %s", session_result.error)

    new_paper_ids: List[str] = []
    new_web_ids: List[str] = []

    already_indexed = set(state.get("indexed_paper_ids", []))
    papers = state.get("papers", [])
    to_index = [
        paper
        for paper in papers
        if paper.get("pdf_path")
        and paper["uid"] not in already_indexed
        and Path(paper["pdf_path"]).exists()
    ]

    if to_index:
        task_result = dispatch(
            TaskRequest(
                action="index_pdf_documents",
                params={
                    "persist_dir": persist_dir,
                    "collection_name": paper_collection,
                    "pdfs": [paper["pdf_path"] for paper in to_index],
                    "chunk_size": chunk_size,
                    "overlap": overlap,
                    "run_id": run_id,
                },
            ),
            cfg,
        )
        if task_result.success:
            new_paper_ids = task_result.data.get("indexed_docs", [])
        else:
            logger.error("PDF indexing failed: %s", task_result.error)

    all_submitted_paper_ids = [Path(paper["pdf_path"]).stem for paper in to_index]
    if run_id and all_submitted_paper_ids:
        run_docs_result = dispatch(
            TaskRequest(
                action="upsert_run_doc_records",
                params={
                    "sqlite_path": sqlite_path,
                    "run_id": run_id,
                    "doc_uids": all_submitted_paper_ids,
                    "doc_type": "paper",
                },
            ),
            cfg,
        )
        if not run_docs_result.success:
            logger.warning("run_docs upsert (papers) failed: %s", run_docs_result.error)

    already_web = set(state.get("indexed_web_ids", []))
    web_sources = state.get("web_sources", [])
    to_index_web = [web_source for web_source in web_sources if web_source.get("body") and web_source["uid"] not in already_web]

    for web_source in to_index_web:
        doc_id = web_source["uid"]
        text = web_source["body"]
        if len(text.strip()) < 100:
            continue
        chunks_result = dispatch(
            TaskRequest(
                action="chunk_text",
                params={
                    "text": text,
                    "chunk_size": chunk_size,
                    "overlap": overlap,
                },
            ),
            cfg,
        )
        if not chunks_result.success:
            logger.error("Web chunking failed for %s: %s", doc_id, chunks_result.error)
            continue
        chunks = chunks_result.data.get("chunks", [])
        if not chunks:
            continue
        index_result = dispatch(
            TaskRequest(
                action="build_web_index",
                params={
                    "persist_dir": persist_dir,
                    "collection_name": web_collection,
                    "chunks": chunks,
                    "doc_id": doc_id,
                    "run_id": run_id,
                },
            ),
            cfg,
        )
        if index_result.success:
            new_web_ids.append(doc_id)
        else:
            logger.error("Web indexing failed for %s: %s", doc_id, index_result.error)

    if run_id and new_web_ids:
        run_docs_result = dispatch(
            TaskRequest(
                action="upsert_run_doc_records",
                params={
                    "sqlite_path": sqlite_path,
                    "run_id": run_id,
                    "doc_uids": new_web_ids,
                    "doc_type": "web",
                },
            ),
            cfg,
        )
        if not run_docs_result.success:
            logger.warning("run_docs upsert (web) failed: %s", run_docs_result.error)

    cumulative_paper_ids = list(
        dict.fromkeys(list(state.get("indexed_paper_ids", [])) + new_paper_ids)
    )
    cumulative_web_ids = list(
        dict.fromkeys(list(state.get("indexed_web_ids", [])) + new_web_ids)
    )
    return ns(
        {
            "indexed_paper_ids": cumulative_paper_ids,
            "indexed_web_ids": cumulative_web_ids,
            "status": (
                f"Indexed {len(new_paper_ids)} new PDFs, {len(new_web_ids)} new web pages "
                f"(cumulative: {len(cumulative_paper_ids)} papers, {len(cumulative_web_ids)} web)"
            ),
        }
    )
