from __future__ import annotations

import re
from typing import Any, Dict, List

from src.retrieval.reranker_backends import rerank_hits as rerank_hits_with_backend

_VISUAL_INTENT_TERMS = {
    "figure", "fig", "diagram", "architecture", "plot", "chart",
    "table", "visualization", "illustration", "schematic", "overview",
    "flowchart", "pipeline", "framework",
    "图", "图表", "架构", "流程图", "示意图", "可视化",
}
_FORMULA_INTENT_TERMS = {
    "equation", "formula", "derive", "derivation", "proof",
    "theorem", "lemma", "corollary", "mathematical",
    "公式", "推导", "证明", "定理", "引理",
}
_VISUAL_FIGURE_BONUS = 0.003
_FORMULA_MATH_BONUS = 0.002


def detect_query_intent(query: str) -> str:
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


def apply_intent_prior(hits: List[Dict[str, Any]], intent: str) -> List[Dict[str, Any]]:
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


def reciprocal_rank_fusion(
    *rankings: List[Dict[str, Any]],
    id_key: str = "id",
    k: int = 60,
) -> List[Dict[str, Any]]:
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


def collapse_figure_duplicates(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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


def ensure_figure_presence(
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


def postprocess(
    hits: List[Dict[str, Any]],
    query: str,
    top_k: int,
    reranker_model: str | None = None,
    reranker_backend_name: str = "local_crossencoder",
    cfg: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    intent = detect_query_intent(query)
    if intent != "general":
        hits = apply_intent_prior(hits, intent)
    if reranker_model:
        hits = rerank_hits_with_backend(
            query,
            hits,
            model_name=reranker_model,
            backend_name=reranker_backend_name,
            cfg=cfg,
        )
    hits = collapse_figure_duplicates(hits)
    if intent == "visual":
        hits = ensure_figure_presence(hits, top_k=top_k)
    return hits[:top_k]
