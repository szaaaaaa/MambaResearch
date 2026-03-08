from __future__ import annotations

from typing import Any, Dict, List

from src.ingest.faiss_indexer import _index_path, _require_faiss, load_collection_state
from src.retrieval.chroma_retriever import (
    apply_intent_prior,
    collapse_figure_duplicates,
    detect_query_intent,
    ensure_figure_presence,
    _reciprocal_rank_fusion,
)
from src.retrieval.embeddings import DEFAULT_BACKEND, DEFAULT_MODEL, embed_text
from src.retrieval.reranker_backends import rerank_hits as rerank_hits_with_backend


def retrieve(
    *,
    persist_dir: str,
    collection_name: str,
    query: str,
    top_k: int = 8,
    model_name: str = DEFAULT_MODEL,
    candidate_k: int | None = None,
    reranker_model: str | None = None,
    allowed_doc_ids: list[str] | None = None,
    hybrid: bool = False,
    embedding_backend_name: str = DEFAULT_BACKEND,
    reranker_backend_name: str = "local_crossencoder",
    cfg: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    if top_k <= 0:
        raise ValueError("top_k must be > 0")

    state = load_collection_state(persist_dir=persist_dir, collection_name=collection_name)
    if not state["ids"]:
        return []

    n_results = max(top_k, candidate_k or top_k)
    faiss = _require_faiss()
    index = faiss.read_index(str(_index_path(persist_dir, collection_name)))

    q_emb = embed_text(
        query,
        model_name=model_name,
        backend_name=embedding_backend_name,
        cfg=cfg,
        is_query=True,
    ).astype("float32", copy=False).reshape(1, -1)
    faiss.normalize_L2(q_emb)

    search_k = max(n_results, len(state["ids"]) if allowed_doc_ids else n_results)
    similarities, indices = index.search(q_emb, search_k)

    dense_hits: List[Dict[str, Any]] = []
    for similarity, idx in zip(similarities[0], indices[0]):
        if idx < 0 or idx >= len(state["ids"]):
            continue
        meta = state["metadatas"][idx]
        doc_id = str((meta or {}).get("doc_id", ""))
        if allowed_doc_ids is not None and doc_id not in allowed_doc_ids:
            continue
        dense_hits.append(
            {
                "id": state["ids"][idx],
                "text": state["documents"][idx],
                "meta": meta,
                "distance": float(max(0.0, 1.0 - float(similarity))),
            }
        )
        if len(dense_hits) >= n_results:
            break

    out = dense_hits
    if hybrid:
        from src.retrieval.bm25_index import search_bm25

        bm25_hits = search_bm25(
            persist_dir=persist_dir,
            collection_name=collection_name,
            query=query,
            top_k=n_results,
            allowed_doc_ids=list(allowed_doc_ids) if allowed_doc_ids else None,
        )
        if bm25_hits:
            dense_map = {hit["id"]: hit for hit in dense_hits}
            enriched_bm25: List[Dict[str, Any]] = []
            for hit in bm25_hits:
                if hit["id"] in dense_map:
                    entry = dict(dense_map[hit["id"]])
                    entry["bm25_score"] = hit["bm25_score"]
                    enriched_bm25.append(entry)
                else:
                    enriched_bm25.append({"id": hit["id"], "text": "", "meta": {}, "bm25_score": hit["bm25_score"]})

            fused = _reciprocal_rank_fusion(dense_hits, enriched_bm25)
            state_map = {
                chunk_id: (text, meta)
                for chunk_id, text, meta in zip(
                    state["ids"],
                    state["documents"],
                    state["metadatas"],
                )
            }
            for hit in fused:
                if not hit.get("text") and hit["id"] in state_map:
                    hit["text"], hit["meta"] = state_map[hit["id"]]
            out = [hit for hit in fused if hit.get("text")]

    intent = detect_query_intent(query)
    if intent != "general":
        out = apply_intent_prior(out, intent)
    if reranker_model:
        out = rerank_hits_with_backend(
            query,
            out,
            model_name=reranker_model,
            backend_name=reranker_backend_name,
            cfg=cfg,
        )
    out = collapse_figure_duplicates(out)
    if intent == "visual":
        out = ensure_figure_presence(out, top_k=top_k)
    return out[:top_k]
