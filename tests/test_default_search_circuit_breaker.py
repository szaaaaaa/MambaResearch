from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import patch


def _import_default_search_module():
    module_name = "src.agent.plugins.search.default_search"
    dependency_names = [
        "src.agent.infra.search.sources",
        "src.agent.plugins.registry",
        "src.common.rag_config",
        "src.ingest.fetchers",
    ]
    original_modules = {name: sys.modules.get(name) for name in dependency_names}
    sys.modules.pop(module_name, None)
    for name in dependency_names:
        sys.modules.pop(name, None)

    fake_sources = types.ModuleType("src.agent.infra.search.sources")
    for name in [
        "dedupe_search_results",
        "fetch_arxiv_records",
        "filter_search_results_by_domain",
        "prioritize_search_results",
        "query_bing_web",
        "query_duckduckgo_web",
        "query_github_web",
        "query_google_cse_web",
        "query_google_scholar",
        "query_google_web",
        "query_openalex",
        "query_semantic_scholar",
        "scrape_search_results",
    ]:
        setattr(fake_sources, name, lambda *args, **kwargs: [])

    fake_registry = types.ModuleType("src.agent.plugins.registry")
    fake_registry.register_search_backend = lambda *args, **kwargs: None

    fake_rag_cfg = types.ModuleType("src.common.rag_config")
    fake_rag_cfg.ingest_latex_download_source = lambda cfg: False
    fake_rag_cfg.ingest_latex_source_dir = lambda root, cfg: "data/sources"

    fake_fetchers = types.ModuleType("src.ingest.fetchers")
    fake_fetchers.download_pdf = lambda *args, **kwargs: None

    sys.modules["src.agent.infra.search.sources"] = fake_sources
    sys.modules["src.agent.plugins.registry"] = fake_registry
    sys.modules["src.common.rag_config"] = fake_rag_cfg
    sys.modules["src.ingest.fetchers"] = fake_fetchers
    try:
        return importlib.import_module(module_name)
    finally:
        for name in dependency_names:
            original = original_modules.get(name)
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


default_search = _import_default_search_module()


class DefaultSearchCircuitBreakerTest(unittest.TestCase):
    def test_open_circuit_skips_provider_call(self) -> None:
        class _FakeBreaker:
            def allow(self, provider: str) -> bool:
                return provider != "arxiv"

            def record_failure(self, provider: str, error: str) -> None:
                raise AssertionError("record_failure should not be called when provider is skipped")

            def record_success(self, provider: str) -> None:
                raise AssertionError("record_success should not be called when provider is skipped")

        cfg = {
            "fetch": {"polite_delay_sec": 0.0},
            "agent": {"papers_per_query": 2, "source_ranking": {"max_per_venue": 2}},
            "providers": {"search": {"academic_order": [], "query_all_academic": False}},
            "sources": {
                "arxiv": {"enabled": True, "max_results_per_query": 2, "download_pdf": False},
                "openalex": {"enabled": False},
                "google_scholar": {"enabled": False},
                "semantic_scholar": {"enabled": False},
                "web": {"enabled": False},
            },
            "paths": {"papers_dir": "data/papers"},
            "metadata_store": {"sqlite_path": "data/metadata/papers.sqlite"},
            "ingest": {"latex": {"source_dir": "data/sources", "download_source": False}},
        }

        backend = default_search.DefaultSearchBackend()

        with patch.object(default_search, "get_provider_circuit_breaker", return_value=_FakeBreaker()):
            with patch.object(
                default_search,
                "fetch_arxiv_records",
                side_effect=AssertionError("fetch_arxiv_records should have been skipped"),
            ):
                out = backend.fetch(
                    cfg=cfg,
                    root=".",
                    academic_queries=["transformer"],
                    web_queries=[],
                    query_routes={},
                )

        self.assertEqual(out["papers"], [])
        self.assertEqual(out["web_sources"], [])


if __name__ == "__main__":
    unittest.main()
