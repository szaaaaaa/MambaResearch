from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List

_LOCAL_CROSS_ENCODER_BACKENDS = {"local_crossencoder", "crossencoder", "local"}


def _normalize_backend_name(backend_name: str) -> str:
    raw = str(backend_name or "local_crossencoder").strip().lower()
    if raw in _LOCAL_CROSS_ENCODER_BACKENDS:
        return "local_crossencoder"
    if raw == "disabled":
        return "disabled"
    return raw


@lru_cache(maxsize=2)
def _get_local_reranker(model_name: str):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name)


def rerank_hits(
    query: str,
    hits: List[Dict[str, Any]],
    *,
    model_name: str,
    backend_name: str = "local_crossencoder",
) -> List[Dict[str, Any]]:
    if not hits:
        return []

    backend = _normalize_backend_name(backend_name)
    if backend == "disabled" or not model_name:
        return list(hits)
    if backend != "local_crossencoder":
        raise ValueError(f"Unsupported reranker backend '{backend_name}'")

    model = _get_local_reranker(model_name)
    pairs = [(query, hit["text"]) for hit in hits]
    scores = model.predict(pairs)

    reranked: List[Dict[str, Any]] = []
    for hit, score in zip(hits, scores):
        entry = dict(hit)
        entry["reranker_score"] = float(score)
        reranked.append(entry)
    reranked.sort(key=lambda item: item["reranker_score"], reverse=True)
    return reranked
