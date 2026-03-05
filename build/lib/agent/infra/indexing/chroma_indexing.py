from __future__ import annotations

from pathlib import Path
from typing import Iterable, List


def chunk_text(text: str, *, chunk_size: int, overlap: int):
    from src.ingest.chunking import chunk_text as _chunk_text

    return _chunk_text(text, chunk_size=chunk_size, overlap=overlap)


def index_pdf_documents(
    *,
    persist_dir: str,
    collection_name: str,
    pdfs: Iterable[Path],
    chunk_size: int,
    overlap: int,
    run_id: str,
    embedding_model: str = "all-MiniLM-L6-v2",
    build_bm25: bool = False,
    root: Path | None = None,
    cfg: dict | None = None,
):
    from src.workflows.traditional_rag import index_pdfs

    return index_pdfs(
        persist_dir=persist_dir,
        collection_name=collection_name,
        pdfs=pdfs,
        chunk_size=chunk_size,
        overlap=overlap,
        run_id=run_id,
        embedding_model=embedding_model,
        build_bm25=build_bm25,
        root=root,
        cfg=cfg,
    )


def build_web_index(
    *,
    persist_dir: str,
    collection_name: str,
    chunks: List[str],
    doc_id: str,
    run_id: str,
    embedding_model: str = "all-MiniLM-L6-v2",
    build_bm25: bool = False,
):
    from src.ingest.indexer import build_chroma_index

    return build_chroma_index(
        persist_dir=persist_dir,
        collection_name=collection_name,
        chunks=chunks,
        doc_id=doc_id,
        run_id=run_id,
        embedding_model=embedding_model,
        build_bm25=build_bm25,
    )


def init_run_tracking(sqlite_path: str) -> None:
    from src.ingest.fetchers import init_run_tables

    init_run_tables(sqlite_path)


def upsert_run_session_record(sqlite_path: str, *, run_id: str, topic: str) -> None:
    from src.ingest.fetchers import upsert_run_session

    upsert_run_session(sqlite_path, run_id=run_id, topic=topic)


def upsert_run_doc_records(
    sqlite_path: str,
    *,
    run_id: str,
    doc_uids: List[str],
    doc_type: str,
) -> None:
    from src.ingest.fetchers import upsert_run_docs

    upsert_run_docs(sqlite_path, run_id=run_id, doc_uids=doc_uids, doc_type=doc_type)
