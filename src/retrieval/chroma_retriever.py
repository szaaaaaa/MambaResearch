from __future__ import annotations

from typing import Any, Dict, List

from src.retrieval.common import (
    apply_intent_prior,
    collapse_figure_duplicates,
    detect_query_intent,
    ensure_figure_presence,
    postprocess,
    reciprocal_rank_fusion,
)
from src.retrieval.embeddings import DEFAULT_BACKEND, DEFAULT_MODEL, embed_text


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
    import chromadb

    if top_k <= 0:
        raise ValueError("top_k must be > 0")

    if candidate_k is None and reranker_model:
        candidate_k = max(top_k * 3, top_k)
    n_results = max(top_k, candidate_k or top_k)

    client = chromadb.PersistentClient(path=persist_dir)
    col = client.get_collection(name=collection_name)

    q_emb = embed_text(
        query,
        model_name=model_name,
        backend_name=embedding_backend_name,
        cfg=cfg,
        is_query=True,
    ).tolist()
    where = {"doc_id": {"$in": list(allowed_doc_ids)}} if allowed_doc_ids else None

    try:
        res = col.query(
            query_embeddings=[q_emb],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        if where is not None:
            try:
                res = col.query(
                    query_embeddings=[q_emb],
                    n_results=1,
                    where=where,
                    include=["documents", "metadatas", "distances"],
                )
            except Exception:
                return []
        else:
            raise

    dense_hits: List[Dict[str, Any]] = []
    for _id, doc, meta, dist in zip(
        res["ids"][0],
        res["documents"][0],
        res["metadatas"][0],
        res["distances"][0],
    ):
        dense_hits.append({"id": _id, "text": doc, "meta": meta, "distance": float(dist)})

    out = dense_hits
    if hybrid and persist_dir and collection_name:
        from src.retrieval.bm25_index import search_bm25

        bm25_hits = search_bm25(
            persist_dir=persist_dir,
            collection_name=collection_name,
            query=query,
            top_k=n_results,
            allowed_doc_ids=list(allowed_doc_ids) if allowed_doc_ids else None,
        )
        if bm25_hits:
            dense_map = {h["id"]: h for h in dense_hits}
            enriched_bm25: List[Dict[str, Any]] = []
            for bh in bm25_hits:
                if bh["id"] in dense_map:
                    entry = dict(dense_map[bh["id"]])
                    entry["bm25_score"] = bh["bm25_score"]
                    enriched_bm25.append(entry)
                else:
                    enriched_bm25.append({"id": bh["id"], "text": "", "meta": {}, "bm25_score": bh["bm25_score"]})

            fused = reciprocal_rank_fusion(dense_hits, enriched_bm25)

            missing_ids = [h["id"] for h in fused if not h.get("text")]
            if missing_ids:
                try:
                    extra = col.get(ids=missing_ids, include=["documents", "metadatas"])
                    extra_map = {}
                    for eid, edoc, emeta in zip(extra["ids"], extra["documents"], extra["metadatas"]):
                        extra_map[eid] = {"text": edoc, "meta": emeta}
                    for h in fused:
                        if h["id"] in extra_map:
                            h["text"] = extra_map[h["id"]]["text"]
                            h["meta"] = extra_map[h["id"]]["meta"]
                except Exception:
                    pass

            out = [h for h in fused if h.get("text")]

    return postprocess(
        out, query, top_k,
        reranker_model=reranker_model,
        reranker_backend_name=reranker_backend_name,
        cfg=cfg,
    )
