from __future__ import annotations

import unittest

from src.agent.core.config import normalize_and_validate_config
from src.common.rag_config import (
    retrieval_effective_embedding_model,
    retrieval_embedding_backend,
    retrieval_reranker_backend,
    retrieval_runtime_mode,
)
from src.rag.reranker_backends import rerank_hits


class RuntimeModesTest(unittest.TestCase):
    def test_rag_config_selects_remote_model_for_openai_backend(self) -> None:
        cfg = normalize_and_validate_config(
            {
                "retrieval": {
                    "runtime_mode": "lite",
                    "embedding_backend": "openai_embedding",
                    "embedding_model": "all-MiniLM-L6-v2",
                    "remote_embedding_model": "text-embedding-3-small",
                }
            }
        )

        self.assertEqual(retrieval_runtime_mode(cfg), "lite")
        self.assertEqual(retrieval_embedding_backend(cfg), "openai_embedding")
        self.assertEqual(retrieval_effective_embedding_model(cfg), "text-embedding-3-small")
        self.assertEqual(retrieval_reranker_backend(cfg), "disabled")

    def test_disabled_reranker_is_noop(self) -> None:
        hits = [
            {"id": "a", "text": "alpha", "rrf_score": 0.9},
            {"id": "b", "text": "beta", "rrf_score": 0.8},
        ]

        reranked = rerank_hits("query", hits, model_name="unused", backend_name="disabled")

        self.assertEqual(reranked, hits)


if __name__ == "__main__":
    unittest.main()
