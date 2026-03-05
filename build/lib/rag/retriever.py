from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List

import numpy as np

from src.rag.embeddings import DEFAULT_MODEL, embed_text


@lru_cache(maxsize=2)
def _get_reranker(model_name: str):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name)


def rerank_hits(query: str, hits: List[Dict[str, Any]], model_name: str) -> List[Dict[str, Any]]:
    if not hits:
        return []
    model = _get_reranker(model_name)
    pairs = [(query, h["text"]) for h in hits]
    scores = model.predict(pairs)
    out: List[Dict[str, Any]] = []
    for h, s in zip(hits, scores):
        x = dict(h)
        x["reranker_score"] = float(s)
        out.append(x)
    out.sort(key=lambda x: x["reranker_score"], reverse=True)
    return out


def _reciprocal_rank_fusion(
    *rankings: List[Dict[str, Any]],
    id_key: str = "id",
    k: int = 60,
) -> List[Dict[str, Any]]:
    """Merge multiple ranked lists via RRF.  Returns items sorted by fused score."""
    scores: Dict[str, float] = {}
    items: Dict[str, Dict[str, Any]] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            item_id = item[id_key]
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank + 1)
            if item_id not in items:
                items[item_id] = item
    fused = []
    for item_id, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        entry = dict(items[item_id])
        entry["rrf_score"] = score
        fused.append(entry)
    return fused


class Retriever:
    def __init__(self, chroma_collection, model_name: str = DEFAULT_MODEL):
        self.col = chroma_collection
        self.model_name = model_name

    def retrieve(
        self,
        query: str,
        top_k: int = 8,
        candidate_k: int | None = None,
        reranker_model: str | None = None,
        allowed_doc_ids: list[str] | None = None,
        hybrid: bool = False,
        persist_dir: str | None = None,
        collection_name: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant chunks.

        Parameters
        ----------
        allowed_doc_ids:
            When provided, restricts retrieval to chunks whose ``doc_id``
            metadata field is in this list (run_view isolation).  Pass
            ``None`` to query the entire collection (traditional RAG mode).
        hybrid:
            When True, also run BM25 search and fuse results via RRF.
            Requires ``persist_dir`` and ``collection_name``.
        """
        if top_k <= 0:
            raise ValueError("top_k must be > 0")

        if candidate_k is None and reranker_model:
            candidate_k = max(top_k * 3, top_k)
        n_results = max(top_k, candidate_k or top_k)

        # --- Dense retrieval via Chroma ---
        q_emb = embed_text(query, model_name=self.model_name, is_query=True).tolist()
        where = {"doc_id": {"$in": list(allowed_doc_ids)}} if allowed_doc_ids else None

        try:
            res = self.col.query(
                query_embeddings=[q_emb],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            if where is not None:
                try:
                    res = self.col.query(
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

        # --- Optional BM25 hybrid ---
        if hybrid and persist_dir and collection_name:
            from src.rag.bm25_index import search_bm25

            bm25_hits = search_bm25(
                persist_dir=persist_dir,
                collection_name=collection_name,
                query=query,
                top_k=n_results,
                allowed_doc_ids=list(allowed_doc_ids) if allowed_doc_ids else None,
            )
            if bm25_hits:
                # Enrich BM25 hits with text/meta from dense results for reranker
                dense_map = {h["id"]: h for h in dense_hits}
                enriched_bm25: List[Dict[str, Any]] = []
                for bh in bm25_hits:
                    if bh["id"] in dense_map:
                        entry = dict(dense_map[bh["id"]])
                        entry["bm25_score"] = bh["bm25_score"]
                        enriched_bm25.append(entry)
                    else:
                        enriched_bm25.append({"id": bh["id"], "text": "", "meta": {}, "bm25_score": bh["bm25_score"]})

                fused = _reciprocal_rank_fusion(dense_hits, enriched_bm25)

                # Fill in missing text/meta from Chroma for BM25-only hits
                missing_ids = [h["id"] for h in fused if not h.get("text")]
                if missing_ids:
                    try:
                        extra = self.col.get(ids=missing_ids, include=["documents", "metadatas"])
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
            else:
                out = dense_hits
        else:
            out = dense_hits

        if reranker_model:
            out = rerank_hits(query, out, reranker_model)
        return out[:top_k]


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
) -> List[Dict[str, Any]]:
    import chromadb

    client = chromadb.PersistentClient(path=persist_dir)
    col = client.get_collection(name=collection_name)
    return Retriever(col, model_name=model_name).retrieve(
        query=query,
        top_k=top_k,
        candidate_k=candidate_k,
        reranker_model=reranker_model,
        allowed_doc_ids=allowed_doc_ids,
        hybrid=hybrid,
        persist_dir=persist_dir,
        collection_name=collection_name,
    )
