from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from src.agent.core.schemas import SearchFetchResult
from src.agent.infra.search.sources import (
    dedupe_search_results,
    fetch_arxiv_records,
    filter_search_results_by_domain,
    prioritize_search_results,
    query_bing_web,
    query_duckduckgo_web,
    query_github_web,
    query_google_cse_web,
    query_google_scholar,
    query_google_web,
    query_openalex,
    query_semantic_scholar,
    scrape_search_results,
)
from src.agent.plugins.registry import register_search_backend

logger = logging.getLogger(__name__)


def _source_enabled(cfg: Dict[str, Any], source_name: str) -> bool:
    return cfg.get("sources", {}).get(source_name, {}).get("enabled", True)


def _academic_provider_order(cfg: Dict[str, Any]) -> List[str]:
    order = cfg.get("providers", {}).get("search", {}).get("academic_order")
    if isinstance(order, list) and order:
        return [str(x).strip().lower() for x in order if str(x).strip()]
    return ["openalex", "google_scholar", "semantic_scholar"]


def _web_provider_order(cfg: Dict[str, Any]) -> List[str]:
    order = cfg.get("providers", {}).get("search", {}).get("web_order")
    if isinstance(order, list) and order:
        return [str(x).strip().lower() for x in order if str(x).strip()]

    prefer_google = cfg.get("sources", {}).get("web", {}).get("prefer_google", True)
    if prefer_google:
        return ["google_cse", "bing", "duckduckgo", "google", "github"]
    return ["duckduckgo", "bing", "google_cse", "google", "github"]


class DefaultSearchBackend:
    def fetch(
        self,
        *,
        cfg: Dict[str, Any],
        root: Path | str,
        academic_queries: List[str],
        web_queries: List[str],
        query_routes: Dict[str, Dict[str, Any]],
    ) -> SearchFetchResult:
        root = Path(root)
        sources_cfg = cfg.get("sources", {})
        delay = float(cfg.get("fetch", {}).get("polite_delay_sec", 1.0))
        search_provider_cfg = cfg.get("providers", {}).get("search", {})

        new_papers: List[Dict[str, Any]] = []
        new_web: List[Dict[str, Any]] = []
        seen_papers: set[str] = set()
        seen_web: set[str] = set()

        if _source_enabled(cfg, "arxiv"):
            arxiv_cfg = sources_cfg.get("arxiv", {})
            per_query = int(
                arxiv_cfg.get(
                    "max_results_per_query",
                    cfg.get("agent", {}).get("papers_per_query", 5),
                )
            )
            download_default = bool(arxiv_cfg.get("download_pdf", True))

            papers_dir = str((root / cfg.get("paths", {}).get("papers_dir", "data/papers")).resolve())
            sqlite_path = str(
                (root / cfg.get("metadata_store", {}).get("sqlite_path", "data/metadata/papers.sqlite")).resolve()
            )

            for q in academic_queries:
                logger.info("[arXiv] Searching: %s (max %d)", q, per_query)
                try:
                    route = query_routes.get(q, {})
                    records = fetch_arxiv_records(
                        query=q,
                        sqlite_path=sqlite_path,
                        papers_dir=papers_dir,
                        max_results=per_query,
                        download=bool(route.get("download_pdf", download_default)),
                        polite_delay_sec=delay,
                    )
                    for r in records:
                        if r.uid in seen_papers:
                            continue
                        new_papers.append(
                            {
                                "uid": r.uid,
                                "title": r.title,
                                "authors": r.authors,
                                "year": r.year,
                                "abstract": r.abstract,
                                "pdf_path": r.pdf_path,
                                "source": "arxiv",
                            }
                        )
                        seen_papers.add(r.uid)
                except Exception as e:  # pragma: no cover - network path
                    logger.error("[arXiv] Failed for '%s': %s", q, e)

        if (
            _source_enabled(cfg, "openalex")
            or _source_enabled(cfg, "google_scholar")
            or _source_enabled(cfg, "semantic_scholar")
        ):
            order = _academic_provider_order(cfg)
            query_all = bool(search_provider_cfg.get("query_all_academic", False))

            gs_cfg = sources_cfg.get("google_scholar", {})
            s2_cfg = sources_cfg.get("semantic_scholar", {})
            oa_cfg = sources_cfg.get("openalex", {})
            target_per_query = int(cfg.get("agent", {}).get("papers_per_query", 5))
            gs_per_query = int(gs_cfg.get("max_results_per_query", target_per_query))
            s2_per_query = int(s2_cfg.get("max_results_per_query", target_per_query))
            oa_per_query = int(oa_cfg.get("max_results_per_query", target_per_query))

            for q in academic_queries:
                merged_results = []
                for provider in order:
                    unique_now = len(dedupe_search_results(merged_results))
                    need_more = max(0, target_per_query - unique_now)
                    if provider == "openalex" and _source_enabled(cfg, "openalex"):
                        if need_more == 0 and merged_results and not query_all:
                            continue
                        oa_max = max(oa_per_query, need_more)
                        logger.info("[OpenAlex] Searching: %s (max %d)", q, oa_max)
                        try:
                            merged_results.extend(query_openalex(q, max_results=oa_max))
                        except Exception as e:  # pragma: no cover - network path
                            logger.error("[OpenAlex] Failed for '%s': %s", q, e)
                    elif provider == "google_scholar" and _source_enabled(cfg, "google_scholar"):
                        logger.info("[Google Scholar] Searching: %s (max %d)", q, gs_per_query)
                        try:
                            merged_results.extend(query_google_scholar(q, max_results=gs_per_query))
                        except Exception as e:  # pragma: no cover - network path
                            logger.error("[Google Scholar] Failed for '%s': %s", q, e)
                    elif provider == "semantic_scholar" and _source_enabled(cfg, "semantic_scholar"):
                        if need_more == 0 and merged_results and not query_all:
                            continue
                        s2_max = max(s2_per_query, need_more)
                        logger.info("[Semantic Scholar] Searching: %s (max %d)", q, s2_max)
                        try:
                            merged_results.extend(query_semantic_scholar(q, max_results=s2_max))
                        except Exception as e:  # pragma: no cover - network path
                            logger.error("[Semantic Scholar] Failed for '%s': %s", q, e)

                final_results = dedupe_search_results(merged_results)[: max(target_per_query, gs_per_query, s2_per_query, oa_per_query)]
                for r in final_results:
                    if r.uid in seen_papers:
                        continue
                    new_papers.append(
                        {
                            "uid": r.uid,
                            "title": r.title,
                            "authors": r.authors,
                            "year": r.year,
                            "abstract": r.snippet,
                            "pdf_path": None,
                            "pdf_url": r.pdf_url,
                            "url": r.url,
                            "source": r.source,
                        }
                    )
                    seen_papers.add(r.uid)

        if _source_enabled(cfg, "web"):
            order = _web_provider_order(cfg)
            query_all = bool(search_provider_cfg.get("query_all_web", False))

            web_cfg = sources_cfg.get("web", {})
            per_query = int(web_cfg.get("max_results_per_query", 8))
            overfetch = int(web_cfg.get("overfetch_factor", 3))
            do_scrape = bool(web_cfg.get("scrape_pages", True))
            scrape_max = int(web_cfg.get("scrape_max_chars", 30000))
            web_delay = float(web_cfg.get("polite_delay_sec", 0.5))
            ddg_region = str(web_cfg.get("ddg_region", "us-en"))
            google_hl = str(web_cfg.get("google_hl", "en"))
            google_gl = str(web_cfg.get("google_gl", "us"))
            bing_mkt = str(web_cfg.get("bing_mkt", "en-US"))
            github_sort = str(web_cfg.get("github_sort", "stars"))
            prefer_english = bool(web_cfg.get("prefer_english", True))
            max_zh_ratio = float(web_cfg.get("max_chinese_ratio", 0.25))
            blocked_domains = web_cfg.get("blocked_domains", [])

            for q in web_queries:
                logger.info("[Web] Searching: %s (max %d)", q, per_query)
                try:
                    merged = []
                    raw_n = max(per_query * max(1, overfetch), per_query)
                    for provider in order:
                        enough = len(dedupe_search_results(merged)) >= per_query
                        if enough and not query_all:
                            break

                        if provider == "google" and _source_enabled(cfg, "web"):
                            merged.extend(query_google_web(q, max_results=raw_n, hl=google_hl, gl=google_gl))
                        elif provider == "google_cse" and _source_enabled(cfg, "google_cse"):
                            merged.extend(query_google_cse_web(q, max_results=raw_n, hl=google_hl, gl=google_gl))
                        elif provider == "bing" and _source_enabled(cfg, "bing"):
                            merged.extend(query_bing_web(q, max_results=raw_n, mkt=bing_mkt))
                        elif provider == "duckduckgo" and _source_enabled(cfg, "web"):
                            merged.extend(query_duckduckgo_web(q, max_results=raw_n, region=ddg_region))
                        elif provider == "github" and _source_enabled(cfg, "github"):
                            merged.extend(query_github_web(q, max_results=raw_n, sort=github_sort))

                    results = dedupe_search_results(merged)
                    results = filter_search_results_by_domain(results, blocked_domains=blocked_domains)
                    results = prioritize_search_results(
                        results,
                        max_results=per_query,
                        prefer_english=prefer_english,
                        max_chinese_ratio=max_zh_ratio,
                    )
                    if do_scrape:
                        results = scrape_search_results(
                            results,
                            polite_delay_sec=web_delay,
                            max_chars=scrape_max,
                        )
                    for r in results:
                        if r.uid in seen_web:
                            continue
                        new_web.append(
                            {
                                "uid": r.uid,
                                "title": r.title,
                                "url": r.url,
                                "snippet": r.snippet,
                                "body": r.body,
                                "source": r.source,
                            }
                        )
                        seen_web.add(r.uid)
                except Exception as e:  # pragma: no cover - network path
                    logger.error("[Web] Failed for '%s': %s", q, e)

        return {
            "papers": new_papers,
            "web_sources": new_web,
        }


register_search_backend("default_search", DefaultSearchBackend())
