from __future__ import annotations

from typing import Any, Dict, List

from src.agent.infra.retrieval.chroma_retriever import retrieve_chunks as infra_retrieve_chunks
from src.agent.plugins.registry import register_retriever_backend
from src.common.rag_config import (
    retrieval_effective_embedding_model,
    retrieval_embedding_backend,
    retrieval_reranker_backend,
)
from src.rag.embeddings import DEFAULT_MODEL


class DefaultRetrieverBackend:
    def retrieve(
        self,
        *,
        persist_dir: str,
        collection_name: str,
        query: str,
        top_k: int,
        candidate_k: int | None,
        reranker_model: str | None,
        allowed_doc_ids: List[str] | None,
        cfg: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        retrieval_cfg = cfg.get("retrieval", {})
        embedding_model = retrieval_effective_embedding_model(
            cfg,
            str(retrieval_cfg.get("embedding_model", DEFAULT_MODEL)),
        )
        embedding_backend = retrieval_embedding_backend(cfg)
        reranker_backend = retrieval_reranker_backend(cfg)
        hybrid = bool(retrieval_cfg.get("hybrid", False))
        return infra_retrieve_chunks(
            persist_dir=persist_dir,
            collection_name=collection_name,
            query=query,
            top_k=top_k,
            candidate_k=candidate_k,
            reranker_model=reranker_model,
            allowed_doc_ids=allowed_doc_ids,
            embedding_model=embedding_model,
            hybrid=hybrid,
            embedding_backend_name=embedding_backend,
            reranker_backend_name=reranker_backend,
            cfg=cfg,
        )


register_retriever_backend("default_retriever", DefaultRetrieverBackend())
