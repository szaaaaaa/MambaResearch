# src/ingest/indexer.py
from __future__ import annotations

from typing import List, Dict, Any
from pathlib import Path

import chromadb

from src.ingest.chunking import Chunk
from src.rag.embeddings import DEFAULT_BACKEND, DEFAULT_MODEL, embed_texts


def _coerce_chunk(chunk: Any, idx: int) -> Chunk:
    if isinstance(chunk, Chunk):
        return chunk
    if isinstance(chunk, dict):
        return Chunk(
            chunk_id=str(chunk.get("chunk_id") or f"chunk_{idx:06d}"),
            text=str(chunk.get("text", "")),
            start_char=int(chunk.get("start_char", 0)),
            end_char=int(chunk.get("end_char", 0)),
            metadata=dict(chunk.get("metadata") or {}),
        )
    if hasattr(chunk, "text"):
        return Chunk(
            chunk_id=str(getattr(chunk, "chunk_id", f"chunk_{idx:06d}")),
            text=str(getattr(chunk, "text", "")),
            start_char=int(getattr(chunk, "start_char", 0)),
            end_char=int(getattr(chunk, "end_char", 0)),
            metadata=dict(getattr(chunk, "metadata", {}) or {}),
        )
    text = str(chunk)
    return Chunk(
        chunk_id=f"chunk_{idx:06d}",
        text=text,
        start_char=0,
        end_char=len(text),
        metadata={},
    )


def build_chroma_index(
    *,
    persist_dir: str,
    collection_name: str,
    chunks: List[Chunk],
    doc_id: str,
    run_id: str = "",
    embedding_model: str = DEFAULT_MODEL,
    embedding_backend: str = DEFAULT_BACKEND,
    build_bm25: bool = False,
    cfg: Dict[str, Any] | None = None,
) -> int:
    """Index chunks into Chroma.

    When ``run_id`` is provided (agent mode), performs a cross-run dedup check:
    if this ``doc_id`` is already present in the collection it is skipped
    entirely so documents are stored only once globally.
    """
    Path(persist_dir).mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=persist_dir)

    col = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    # Cross-run dedup: if this doc is already in the collection, skip re-embedding.
    if run_id:
        try:
            existing = col.get(where={"doc_id": doc_id}, include=[], limit=1)
            if existing and existing.get("ids"):
                return 0  # already indexed globally, reuse existing chunks
        except Exception:
            pass  # get() failed — fall through and index normally

    normalized_chunks = [_coerce_chunk(chunk, idx) for idx, chunk in enumerate(chunks)]

    ids = [f"{doc_id}:{chunk.chunk_id}" for chunk in normalized_chunks]
    docs = [chunk.text for chunk in normalized_chunks]
    metas: List[Dict[str, Any]] = [
        {
            "doc_id": doc_id,
            "chunk_id": chunk.chunk_id,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
            "run_id": run_id,
            "chunk_type": "figure" if chunk.start_char == -1 else "text",
            **(chunk.metadata or {}),
        }
        for chunk in normalized_chunks
    ]
    embeddings = embed_texts(
        docs,
        model_name=embedding_model,
        backend_name=embedding_backend,
        cfg=cfg,
    ).tolist()

    col.add(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)

    if build_bm25:
        from src.rag.bm25_index import build_bm25_sidecar

        build_bm25_sidecar(persist_dir, collection_name, ids, docs)

    return len(normalized_chunks)
