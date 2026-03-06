from __future__ import annotations

import re
from typing import Any, Dict, List

from src.rag.embeddings import DEFAULT_BACKEND, DEFAULT_MODEL, embed_text
from src.rag.reranker_backends import rerank_hits as rerank_hits_with_backend

_VISUAL_INTENT_TERMS = {
    "figure", "fig", "diagram", "architecture", "plot", "chart",
    "table", "visualization", "illustration", "schematic", "overview",
    "flowchart", "pipeline", "framework",
    "图", "图表", "架构图", "流程图", "示意图", "框架图",
}
_FORMULA_INTENT_TERMS = {
    "equation", "formula", "derive", "derivation", "proof",
    "theorem", "lemma", "corollary", "mathematical",
    "公式", "方程", "推导", "证明", "定理",
}
_VISUAL_FIGURE_BONUS = 0.003
_FORMULA_MATH_BONUS = 0.002


def _detect_query_intent(query: str) -> str:
    q_lower = str(query or "").lower()
    tokens = set(re.findall(r"[a-zA-Z\u4e00-\u9fff]+", q_lower))
    if (tokens & _VISUAL_INTENT_TERMS) or any(term in q_lower for term in _VISUAL_INTENT_TERMS if any("\u4e00" <= ch <= "\u9fff" for ch in term)):
        return "visual"
    if (tokens & _FORMULA_INTENT_TERMS) or any(term in q_lower for term in _FORMULA_INTENT_TERMS if any("\u4e00" <= ch <= "\u9fff" for ch in term)):
        return "formula"
    return "general"


def _has_math_density(text: str, threshold: float = 0.05) -> bool:
    if not text:
        return False
    math_chars = sum(1 for c in text if c in "$\\^_{}")
    return (math_chars / max(1, len(text))) > threshold


def _base_rank_score(hit: Dict[str, Any]) -> float:
    if "rrf_score" in hit:
        return float(hit["rrf_score"])
    if "reranker_score" in hit:
        return float(hit["reranker_score"])
    if "distance" in hit:
        return 1.0 / (1.0 + max(0.0, float(hit["distance"])))
    if "bm25_score" in hit:
        return float(hit["bm25_score"])
    return 0.0


def _apply_intent_prior(hits: List[Dict[str, Any]], intent: str) -> List[Dict[str, Any]]:
    if intent == "general":
        return hits

    boosted: List[Dict[str, Any]] = []
    for hit in hits:
        entry = dict(hit)
        meta = entry.get("meta", {}) or {}
        chunk_type = str(meta.get("chunk_type", "text"))

        bonus = 0.0
        if intent == "visual" and chunk_type == "figure":
            bonus = _VISUAL_FIGURE_BONUS
        elif intent == "formula" and _has_math_density(entry.get("text", "")):
            bonus = _FORMULA_MATH_BONUS

        entry["_intent_score"] = _base_rank_score(entry) + bonus
        boosted.append(entry)

    boosted.sort(key=lambda x: x.get("_intent_score", 0.0), reverse=True)
    return boosted


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


def _collapse_figure_duplicates(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for hit in hits:
        meta = hit.get("meta", {}) or {}
        if meta.get("chunk_type") != "figure":
            out.append(hit)
            continue
        figure_key = str(meta.get("figure_id") or meta.get("image_path") or "").strip()
        if not figure_key:
            out.append(hit)
            continue
        if figure_key in seen:
            continue
        seen.add(figure_key)
        out.append(hit)
    return out


def _ensure_figure_presence(
    hits: List[Dict[str, Any]],
    *,
    top_k: int,
    min_figure_slots: int = 2,
) -> List[Dict[str, Any]]:
    top = list(hits[:top_k])
    rest = list(hits[top_k:])
    figure_count = sum(1 for hit in top if (hit.get("meta", {}) or {}).get("chunk_type") == "figure")
    if figure_count >= min_figure_slots:
        return hits

    figure_candidates = [hit for hit in rest if (hit.get("meta", {}) or {}).get("chunk_type") == "figure"]
    needed = max(0, min_figure_slots - figure_count)
    for fig_hit in figure_candidates[:needed]:
        for idx in range(len(top) - 1, -1, -1):
            if (top[idx].get("meta", {}) or {}).get("chunk_type") != "figure":
                top[idx] = fig_hit
                break
    return top + rest


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
        embedding_backend_name: str = DEFAULT_BACKEND,
        reranker_backend_name: str = "local_crossencoder",
        cfg: Dict[str, Any] | None = None,
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
        q_emb = embed_text(
            query,
            model_name=self.model_name,
            backend_name=embedding_backend_name,
            cfg=cfg,
            is_query=True,
        ).tolist()
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

        intent = _detect_query_intent(query)
        if intent != "general":
            out = _apply_intent_prior(out, intent)
        if reranker_model:
            out = rerank_hits_with_backend(
                query,
                out,
                model_name=reranker_model,
                backend_name=reranker_backend_name,
            )
        out = _collapse_figure_duplicates(out)
        if intent == "visual":
            out = _ensure_figure_presence(out, top_k=top_k)
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
    embedding_backend_name: str = DEFAULT_BACKEND,
    reranker_backend_name: str = "local_crossencoder",
    cfg: Dict[str, Any] | None = None,
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
        embedding_backend_name=embedding_backend_name,
        reranker_backend_name=reranker_backend_name,
        cfg=cfg,
    )
