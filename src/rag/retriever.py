from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List

import numpy as np
from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=2)
def _get_embedder(model_name: str = "all-MiniLM-L6-v2") -> SentenceTransformer:
    return SentenceTransformer(model_name)


def embed_texts(texts: List[str], model_name: str = "all-MiniLM-L6-v2") -> np.ndarray:
    model = _get_embedder(model_name)
    vecs = model.encode(
        texts,
        batch_size=64,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(vecs, dtype=np.float32)


def embed_text(text: str, model_name: str = "all-MiniLM-L6-v2") -> np.ndarray:
    return embed_texts([text], model_name=model_name)[0]


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


class Retriever:
    def __init__(self, chroma_collection, model_name: str = "all-MiniLM-L6-v2"):
        self.col = chroma_collection
        self.model_name = model_name

    def retrieve(
        self,
        query: str,
        top_k: int = 8,
        candidate_k: int | None = None,
        reranker_model: str | None = None,
    ) -> List[Dict[str, Any]]:
        if top_k <= 0:
            raise ValueError("top_k must be > 0")

        if candidate_k is None and reranker_model:
            candidate_k = max(top_k * 3, top_k)
        n_results = max(top_k, candidate_k or top_k)

        q_emb = embed_text(query, model_name=self.model_name).tolist()
        res = self.col.query(
            query_embeddings=[q_emb],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

        out: List[Dict[str, Any]] = []
        for _id, doc, meta, dist in zip(
            res["ids"][0],
            res["documents"][0],
            res["metadatas"][0],
            res["distances"][0],
        ):
            out.append({"id": _id, "text": doc, "meta": meta, "distance": float(dist)})

        if reranker_model:
            out = rerank_hits(query, out, reranker_model)
        return out[:top_k]


def retrieve(
    *,
    persist_dir: str,
    collection_name: str,
    query: str,
    top_k: int = 8,
    model_name: str = "all-MiniLM-L6-v2",
    candidate_k: int | None = None,
    reranker_model: str | None = None,
) -> List[Dict[str, Any]]:
    import chromadb

    client = chromadb.PersistentClient(path=persist_dir)
    col = client.get_collection(name=collection_name)
    return Retriever(col, model_name=model_name).retrieve(
        query=query,
        top_k=top_k,
        candidate_k=candidate_k,
        reranker_model=reranker_model,
    )

