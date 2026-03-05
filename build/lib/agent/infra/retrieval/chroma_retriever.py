from __future__ import annotations

from typing import Any, Dict, List

from src.rag.embeddings import DEFAULT_MODEL
from src.rag.retriever import retrieve


def retrieve_chunks(
    *,
    persist_dir: str,
    collection_name: str,
    query: str,
    top_k: int,
    candidate_k: int | None = None,
    reranker_model: str | None = None,
    allowed_doc_ids: List[str] | None = None,
    embedding_model: str = DEFAULT_MODEL,
    hybrid: bool = False,
) -> List[Dict[str, Any]]:
    return retrieve(
        persist_dir=persist_dir,
        collection_name=collection_name,
        query=query,
        top_k=top_k,
        model_name=embedding_model,
        candidate_k=candidate_k,
        reranker_model=reranker_model,
        allowed_doc_ids=allowed_doc_ids,
        hybrid=hybrid,
    )
