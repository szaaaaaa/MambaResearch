# src/ingest/indexer.py
from __future__ import annotations

from typing import List, Dict, Any
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

from src.ingest.chunking import Chunk
from src.rag.embeddings import DEFAULT_MODEL


def _make_embedding_fn(model_name: str):
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=model_name
    )


def build_chroma_index(
    *,
    persist_dir: str,
    collection_name: str,
    chunks: List[Chunk],
    doc_id: str,
    run_id: str = "",
    embedding_model: str = DEFAULT_MODEL,
    build_bm25: bool = False,
) -> int:
    """Index chunks into Chroma.

    When ``run_id`` is provided (agent mode), performs a cross-run dedup check:
    if this ``doc_id`` is already present in the collection it is skipped
    entirely so documents are stored only once globally.
    """
    Path(persist_dir).mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=persist_dir)

    embedder = _make_embedding_fn(embedding_model)

    col = client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedder,
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

    ids = [f"{doc_id}:{c.chunk_id}" for c in chunks]
    docs = [c.text for c in chunks]
    metas: List[Dict[str, Any]] = [
        {
            "doc_id": doc_id,
            "chunk_id": c.chunk_id,
            "start_char": c.start_char,
            "end_char": c.end_char,
            "run_id": run_id,
            "chunk_type": "figure" if c.start_char == -1 else "text",
            **(c.metadata or {}),
        }
        for c in chunks
    ]

    col.add(ids=ids, documents=docs, metadatas=metas)

    if build_bm25:
        from src.rag.bm25_index import build_bm25_sidecar

        build_bm25_sidecar(persist_dir, collection_name, ids, docs)

    return len(chunks)
