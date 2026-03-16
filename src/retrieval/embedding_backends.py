from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, List

import numpy as np

from src.common.rag_config import retrieval_device

_LOCAL_ST_BACKENDS = {"local_st", "sentence_transformer", "local"}
_OPENAI_BACKENDS = {"openai_embedding", "remote", "remote_embedding"}
_BGE_QUERY_PREFIX = {
    "BAAI/bge-small-en-v1.5": "Represent this sentence: ",
    "BAAI/bge-base-en-v1.5": "Represent this sentence: ",
    "BAAI/bge-large-en-v1.5": "Represent this sentence: ",
}


def _normalize_backend_name(backend_name: str) -> str:
    raw = str(backend_name or "local_st").strip().lower()
    if raw in _LOCAL_ST_BACKENDS:
        return "local_st"
    if raw in _OPENAI_BACKENDS:
        return "openai_embedding"
    if raw == "disabled":
        return "disabled"
    return raw


def _normalize_embeddings(vectors: Any) -> np.ndarray:
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return arr / norms


def _resolve_local_device(cfg: Dict[str, Any] | None) -> str:
    requested = retrieval_device(cfg or {})
    if requested != "auto":
        return requested
    try:
        import torch
    except Exception:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


@lru_cache(maxsize=4)
def _load_local_model(model_name: str, device: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, device=device)


def _add_query_prefix(texts: List[str], model_name: str, *, is_query: bool) -> List[str]:
    if not is_query:
        return texts
    prefix = _BGE_QUERY_PREFIX.get(model_name, "")
    if not prefix:
        return texts
    return [prefix + text for text in texts]


def _embed_with_local_st(
    texts: List[str],
    *,
    model_name: str,
    is_query: bool,
    cfg: Dict[str, Any] | None,
) -> np.ndarray:
    model = _load_local_model(model_name, _resolve_local_device(cfg))
    prepared = _add_query_prefix(texts, model_name, is_query=is_query)
    vectors = model.encode(
        prepared,
        batch_size=64,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(vectors, dtype=np.float32)


@lru_cache(maxsize=4)
def _get_openai_client(api_key_env: str, base_url: str):
    from openai import OpenAI

    kwargs: Dict[str, Any] = {}
    api_key = os.getenv(api_key_env) if api_key_env else None
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _embed_with_openai(
    texts: List[str],
    *,
    model_name: str,
    cfg: Dict[str, Any] | None,
) -> np.ndarray:
    retrieval_cfg = (cfg or {}).get("retrieval", {})
    api_key_env = str(retrieval_cfg.get("openai_api_key_env", "OPENAI_API_KEY")).strip() or "OPENAI_API_KEY"
    base_url = str(retrieval_cfg.get("openai_base_url", "")).strip()
    client = _get_openai_client(api_key_env, base_url)
    response = client.embeddings.create(model=model_name, input=texts)
    vectors = [item.embedding for item in response.data]
    return _normalize_embeddings(vectors)


def embed_texts(
    texts: List[str],
    *,
    backend_name: str,
    model_name: str,
    is_query: bool = False,
    cfg: Dict[str, Any] | None = None,
) -> np.ndarray:
    backend = _normalize_backend_name(backend_name)
    if backend == "local_st":
        return _embed_with_local_st(texts, model_name=model_name, is_query=is_query, cfg=cfg)
    if backend == "openai_embedding":
        return _embed_with_openai(texts, model_name=model_name, cfg=cfg)
    if backend == "disabled":
        raise RuntimeError("Embedding backend is disabled")
    raise ValueError(f"Unsupported embedding backend '{backend_name}'")


def embedding_dim(
    *,
    backend_name: str,
    model_name: str,
    cfg: Dict[str, Any] | None = None,
) -> int:
    backend = _normalize_backend_name(backend_name)
    if backend == "local_st":
        model = _load_local_model(model_name, _resolve_local_device(cfg))
        return int(model.get_sentence_embedding_dimension())
    sample = embed_texts(
        ["dimension probe"],
        backend_name=backend,
        model_name=model_name,
        cfg=cfg,
    )
    return int(sample.shape[1])
