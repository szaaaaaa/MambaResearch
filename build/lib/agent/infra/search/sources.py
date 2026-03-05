from __future__ import annotations

from typing import List

from src.ingest.fetchers import fetch_arxiv_and_store
from src.ingest.web_fetcher import (
    dedup_results,
    filter_results_by_domain,
    prioritize_results,
    scrape_results,
    search_bing,
    search_duckduckgo,
    search_github,
    search_google,
    search_google_cse,
    search_google_scholar,
    search_openalex,
    search_semantic_scholar,
)


def fetch_arxiv_records(
    *,
    query: str,
    sqlite_path: str,
    papers_dir: str,
    max_results: int,
    download: bool,
    download_source: bool,
    source_dir: str,
    polite_delay_sec: float,
):
    return fetch_arxiv_and_store(
        query=query,
        sqlite_path=sqlite_path,
        papers_dir=papers_dir,
        max_results=max_results,
        download=download,
        download_source=download_source,
        source_dir=source_dir,
        polite_delay_sec=polite_delay_sec,
    )


def query_google_scholar(query: str, *, max_results: int):
    return search_google_scholar(query, max_results=max_results)


def query_semantic_scholar(
    query: str,
    *,
    max_results: int,
    min_interval_sec: float = 1.0,
    max_retries: int = 4,
    backoff_sec: float = 1.5,
):
    return search_semantic_scholar(
        query,
        max_results=max_results,
        min_interval_sec=min_interval_sec,
        max_retries=max_retries,
        backoff_sec=backoff_sec,
    )


def query_openalex(query: str, *, max_results: int):
    return search_openalex(query, max_results=max_results)


def query_google_web(query: str, *, max_results: int, hl: str, gl: str):
    return search_google(query, max_results=max_results, hl=hl, gl=gl)


def query_google_cse_web(query: str, *, max_results: int, hl: str, gl: str):
    return search_google_cse(query, max_results=max_results, hl=hl, gl=gl)


def query_bing_web(query: str, *, max_results: int, mkt: str):
    return search_bing(query, max_results=max_results, mkt=mkt)


def query_github_web(query: str, *, max_results: int, sort: str):
    return search_github(query, max_results=max_results, sort=sort)


def query_duckduckgo_web(query: str, *, max_results: int, region: str):
    return search_duckduckgo(query, max_results=max_results, region=region)


def dedupe_search_results(results):
    return dedup_results(results)


def filter_search_results_by_domain(results, *, blocked_domains: List[str]):
    return filter_results_by_domain(results, blocked_domains=blocked_domains)


def prioritize_search_results(
    results,
    *,
    max_results: int,
    prefer_english: bool,
    max_chinese_ratio: float,
):
    return prioritize_results(
        results,
        max_results=max_results,
        prefer_english=prefer_english,
        max_chinese_ratio=max_chinese_ratio,
    )


def scrape_search_results(results, *, polite_delay_sec: float, max_chars: int):
    return scrape_results(results, polite_delay_sec=polite_delay_sec, max_chars=max_chars)
