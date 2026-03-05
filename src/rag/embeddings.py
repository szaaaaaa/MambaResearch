from __future__ import annotations

from functools import lru_cache
from typing import List

import numpy as np

DEFAULT_MODEL = "all-MiniLM-L6-v2"

# BGE models that benefit from a query instruction prefix.
_BGE_QUERY_PREFIX = {
    "BAAI/bge-small-en-v1.5": "Represent this sentence: ",
    "BAAI/bge-base-en-v1.5": "Represent this sentence: ",
    "BAAI/bge-large-en-v1.5": "Represent this sentence: ",
}


@lru_cache(maxsize=2)
def _load_model(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def _add_prefix(texts: List[str], model_name: str, *, is_query: bool) -> List[str]:
    if not is_query:
        return texts
    prefix = _BGE_QUERY_PREFIX.get(model_name, "")
    if not prefix:
        return texts
    return [prefix + t for t in texts]


def embed_texts(
    texts: List[str],
    model_name: str = DEFAULT_MODEL,
    *,
    is_query: bool = False,
) -> np.ndarray:
    model = _load_model(model_name)
    prepared = _add_prefix(texts, model_name, is_query=is_query)
    vecs = model.encode(
        prepared,
        batch_size=64,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(vecs, dtype=np.float32)


def embed_text(
    text: str,
    model_name: str = DEFAULT_MODEL,
    *,
    is_query: bool = False,
) -> np.ndarray:
    return embed_texts([text], model_name=model_name, is_query=is_query)[0]


def embedding_dim(model_name: str = DEFAULT_MODEL) -> int:
    model = _load_model(model_name)
    return model.get_sentence_embedding_dimension()
