from __future__ import annotations

from typing import Any, Dict, List

from src.retrieval.embeddings import DEFAULT_BACKEND, DEFAULT_MODEL
from src.retrieval.faiss_retriever import retrieve


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
    embedding_backend_name: str = DEFAULT_BACKEND,
    reranker_backend_name: str = "local_crossencoder",
    cfg: Dict[str, Any] | None = None,
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
        embedding_backend_name=embedding_backend_name,
        reranker_backend_name=reranker_backend_name,
        cfg=cfg,
    )
