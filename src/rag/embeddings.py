from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from src.rag.embedding_backends import embedding_dim as backend_embedding_dim
from src.rag.embedding_backends import embed_texts as backend_embed_texts

DEFAULT_MODEL = "all-MiniLM-L6-v2"
DEFAULT_BACKEND = "local_st"


def embed_texts(
    texts: List[str],
    model_name: str = DEFAULT_MODEL,
    *,
    backend_name: str = DEFAULT_BACKEND,
    cfg: Dict[str, Any] | None = None,
    is_query: bool = False,
) -> np.ndarray:
    return backend_embed_texts(
        texts,
        backend_name=backend_name,
        model_name=model_name,
        cfg=cfg,
        is_query=is_query,
    )


def embed_text(
    text: str,
    model_name: str = DEFAULT_MODEL,
    *,
    backend_name: str = DEFAULT_BACKEND,
    cfg: Dict[str, Any] | None = None,
    is_query: bool = False,
) -> np.ndarray:
    return embed_texts(
        [text],
        model_name=model_name,
        backend_name=backend_name,
        cfg=cfg,
        is_query=is_query,
    )[0]


def embedding_dim(
    model_name: str = DEFAULT_MODEL,
    *,
    backend_name: str = DEFAULT_BACKEND,
    cfg: Dict[str, Any] | None = None,
) -> int:
    return backend_embedding_dim(
        backend_name=backend_name,
        model_name=model_name,
        cfg=cfg,
    )
