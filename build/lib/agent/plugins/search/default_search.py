from __future__ import annotations

import hashlib
import logging
import math
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse
from difflib import SequenceMatcher

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
from src.common.rag_config import ingest_latex_download_source, ingest_latex_source_dir
from src.ingest.fetchers import download_pdf

logger = logging.getLogger(__name__)

# Only attempt direct PDF downloads from open-access friendly hosts.
_PDF_DOWNLOAD_ALLOW_HOSTS = {
    "arxiv.org",
    "export.arxiv.org",
    "openreview.net",
    "openaccess.thecvf.com",
    "aclanthology.org",
    "proceedings.mlr.press",
    "jmlr.org",
    "ceur-ws.org",
    "papers.nips.cc",
    "neurips.cc",
}
_PDF_DOMAIN_DENY_CACHE: Dict[str, float] = {}
_PDF_DOMAIN_DENY_TTL_SEC = 1800.0

_TOP_VENUE_HINTS = {
    "neurips",
    "icml",
    "iclr",
    "acl",
    "emnlp",
    "naacl",
    "cvpr",
    "eccv",
    "iccv",
    "kdd",
    "www",
    "thewebconf",
    "aaai",
    "ijcai",
    "sigir",
    "chi",
    "uist",
    "tacl",
    "tpami",
    "nature",
    "science",
}


def _norm_text(text: str) -> str:
    s = re.sub(r"\s+", " ", str(text or "").strip().lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _extract_doi(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    s = s.replace("https://doi.org/", "").replace("http://doi.org/", "").strip()
    if s.lower().startswith("doi:"):
        s = s.split(":", 1)[1]
    return s.lower()


def _extract_doi_from_uid(uid: str) -> str:
    u = str(uid or "").strip().lower()
    if u.startswith("doi:"):
        return _extract_doi(u)
    return ""


def _extract_arxiv_id_from_uid(uid: str) -> str:
    u = str(uid or "").strip().lower()
    if u.startswith("arxiv:"):
        return u.split(":", 1)[1]
    return ""


def _title_year_hash(title: str, year: Any) -> str:
    y = _safe_int(year, 0)
    norm = _norm_text(title)
    return hashlib.sha1(f"{norm}|{y}".encode("utf-8")).hexdigest()[:16]


def _canonical_paper_key(item: Dict[str, Any]) -> str:
    doi = _extract_doi(item.get("doi", "")) or _extract_doi_from_uid(item.get("uid", ""))
    if doi:
        return f"doi:{doi}"
    arxiv_id = str(item.get("arxiv_id") or "").strip().lower() or _extract_arxiv_id_from_uid(item.get("uid", ""))
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    return f"titleyear:{_title_year_hash(item.get('title', ''), item.get('year'))}"


def _make_resolvable_url(uid: str) -> str:
    u = str(uid or "").strip().lower()
    if u.startswith("arxiv:"):
        return f"https://arxiv.org/abs/{u.split(':', 1)[1]}"
    if u.startswith("doi:"):
        return f"https://doi.org/{u.split(':', 1)[1]}"
    return ""


def _paper_from_arxiv_record(record: Any, *, query: str) -> Dict[str, Any]:
    uid = str(record.uid)
    return {
        "uid": uid,
        "title": record.title,
        "authors": list(record.authors or []),
        "year": record.year,
        "abstract": record.abstract or "",
        "pdf_path": record.pdf_path,
        "pdf_url": record.pdf_url,
        "source_path": getattr(record, "source_path", None),
        "url": _make_resolvable_url(uid),
        "source": "arxiv",
        "source_origins": ["arxiv"],
        "query_origins": [query],
        "doi": "",
        "arxiv_id": _extract_arxiv_id_from_uid(uid),
        "venue": "arXiv",
        "journal": "",
        "citation_count": 0,
        "peer_reviewed": False,
        "pdf_source": "arxiv" if record.pdf_path or record.pdf_url else "",
    }


def _paper_from_search_result(result: Any, *, query: str) -> Dict[str, Any]:
    uid = str(getattr(result, "uid", "") or "").strip()
    url = str(getattr(result, "url", "") or "").strip()
    doi = _extract_doi(getattr(result, "doi", "")) or _extract_doi_from_uid(uid)
    arxiv_id = str(getattr(result, "arxiv_id", "") or "").strip().lower() or _extract_arxiv_id_from_uid(uid)
    if not uid:
        if doi:
            uid = f"doi:{doi}"
        elif arxiv_id:
            uid = f"arxiv:{arxiv_id}"
    return {
        "uid": uid,
        "title": str(getattr(result, "title", "") or ""),
        "authors": list(getattr(result, "authors", []) or []),
        "year": getattr(result, "year", None),
        "abstract": str(getattr(result, "snippet", "") or ""),
        "pdf_path": str(getattr(result, "pdf_path", "") or "") or None,
        "pdf_url": str(getattr(result, "pdf_url", "") or "") or None,
        "url": url or _make_resolvable_url(uid),
        "source": str(getattr(result, "source", "") or "unknown"),
        "source_origins": list(getattr(result, "source_origins", []) or [str(getattr(result, "source", "") or "unknown")]),
        "query_origins": [query],
        "doi": doi,
        "arxiv_id": arxiv_id,
        "venue": str(getattr(result, "venue", "") or ""),
        "journal": str(getattr(result, "journal", "") or ""),
        "citation_count": _safe_int(getattr(result, "citation_count", 0), 0),
        "peer_reviewed": bool(getattr(result, "peer_reviewed", False)),
        "pdf_source": "",
    }


def _merge_paper(existing: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(existing)
    for key in (
        "title",
        "abstract",
        "venue",
        "journal",
        "doi",
        "arxiv_id",
        "pdf_url",
        "pdf_path",
        "source_path",
        "url",
    ):
        if not out.get(key) and new.get(key):
            out[key] = new.get(key)
    if not out.get("uid") and new.get("uid"):
        out["uid"] = new["uid"]
    if (not out.get("year")) and new.get("year"):
        out["year"] = new.get("year")
    out["citation_count"] = max(_safe_int(out.get("citation_count"), 0), _safe_int(new.get("citation_count"), 0))
    out["peer_reviewed"] = bool(out.get("peer_reviewed", False) or new.get("peer_reviewed", False))
    out["authors"] = list(dict.fromkeys(list(out.get("authors", []) or []) + list(new.get("authors", []) or [])))
    out["source_origins"] = list(
        dict.fromkeys(list(out.get("source_origins", []) or []) + list(new.get("source_origins", []) or []))
    )
    out["query_origins"] = list(
        dict.fromkeys(list(out.get("query_origins", []) or []) + list(new.get("query_origins", []) or []))
    )
    if not out.get("pdf_source") and new.get("pdf_source"):
        out["pdf_source"] = new.get("pdf_source")
    # Prefer non-arXiv source label when available.
    if str(out.get("source", "")).lower() == "arxiv" and str(new.get("source", "")).lower() != "arxiv":
        out["source"] = new.get("source")
    return out


def _token_overlap_score(query: str, doc_text: str) -> float:
    q_tokens = set(_norm_text(query).split())
    if not q_tokens:
        return 0.0
    d_tokens = set(_norm_text(doc_text).split())
    if not d_tokens:
        return 0.0
    return len(q_tokens & d_tokens) / max(1, len(q_tokens))


def _venue_quality_score(item: Dict[str, Any]) -> float:
    venue = _norm_text(item.get("venue", "") or item.get("journal", ""))
    if any(hint in venue for hint in _TOP_VENUE_HINTS):
        return 1.0
    if item.get("peer_reviewed"):
        return 0.82
    src = str(item.get("source", "")).lower()
    if src in {"openalex", "semantic_scholar", "google_scholar"} and venue:
        return 0.72
    if src == "arxiv":
        return 0.45
    return 0.55


def _peer_review_score(item: Dict[str, Any]) -> float:
    return 1.0 if bool(item.get("peer_reviewed")) else 0.0


def _citation_score(item: Dict[str, Any]) -> float:
    cited = max(0, _safe_int(item.get("citation_count"), 0))
    # Smoothly saturates around 1000 citations.
    return min(1.0, math.log1p(cited) / math.log1p(1000))


def _recency_score(item: Dict[str, Any]) -> float:
    year = _safe_int(item.get("year"), 0)
    if year <= 0:
        return 0.3
    now = datetime.now().year
    age = max(0, now - year)
    return max(0.0, min(1.0, 1.0 - (age / 12.0)))


def _final_paper_score(item: Dict[str, Any], *, query: str) -> float:
    relevance = float(
        item.get("relevance_score")
        or _token_overlap_score(query, f"{item.get('title', '')} {item.get('abstract', '')} {item.get('venue', '')}")
    )
    score = (
        0.55 * relevance
        + 0.20 * _venue_quality_score(item)
        + 0.10 * _peer_review_score(item)
        + 0.10 * _citation_score(item)
        + 0.05 * _recency_score(item)
    )
    return round(float(score), 6)


def _venue_key(item: Dict[str, Any]) -> str:
    venue = _norm_text(item.get("venue", "") or item.get("journal", ""))
    if venue:
        return venue
    return _canonical_paper_key(item)


def _rerank_with_diversity(
    items: List[Dict[str, Any]],
    *,
    query: str,
    top_k: int,
    max_per_venue: int,
) -> List[Dict[str, Any]]:
    for x in items:
        x["final_score"] = _final_paper_score(x, query=query)
    ranked = sorted(items, key=lambda i: float(i.get("final_score", 0.0)), reverse=True)

    out: List[Dict[str, Any]] = []
    venue_cnt: Dict[str, int] = {}
    for x in ranked:
        if len(out) >= top_k:
            break
        vk = _venue_key(x)
        if venue_cnt.get(vk, 0) >= max(1, max_per_venue):
            continue
        venue_cnt[vk] = venue_cnt.get(vk, 0) + 1
        out.append(x)

    if len(out) < top_k:
        used_keys = {_canonical_paper_key(x) for x in out}
        for x in ranked:
            if len(out) >= top_k:
                break
            if _canonical_paper_key(x) in used_keys:
                continue
            out.append(x)
            used_keys.add(_canonical_paper_key(x))
    return out


def _pdf_host_from_url(url: str) -> str:
    try:
        host = urlparse(str(url or "")).netloc.lower().strip()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _resolve_pdf_download_policy(cfg: Dict[str, Any] | None) -> tuple[bool, set[str], float]:
    sources_cfg = (cfg or {}).get("sources", {})
    pdf_cfg = sources_cfg.get("pdf_download", {}) if isinstance(sources_cfg, dict) else {}
    if not isinstance(pdf_cfg, dict):
        pdf_cfg = {}
    only_allowed_hosts = bool(pdf_cfg.get("only_allowed_hosts", True))
    raw_allowed = pdf_cfg.get("allowed_hosts", list(_PDF_DOWNLOAD_ALLOW_HOSTS))
    if isinstance(raw_allowed, list) and raw_allowed:
        allowed_hosts = {
            str(x).strip().lower()
            for x in raw_allowed
            if str(x).strip()
        }
    else:
        allowed_hosts = set(_PDF_DOWNLOAD_ALLOW_HOSTS)
    ttl_sec = float(pdf_cfg.get("forbidden_host_ttl_sec", _PDF_DOMAIN_DENY_TTL_SEC))
    return only_allowed_hosts, allowed_hosts, ttl_sec


def _is_pdf_host_whitelisted(host: str, allowed_hosts: set[str]) -> bool:
    h = str(host or "").lower().strip()
    if not h:
        return False
    return any(h == d or h.endswith(f".{d}") for d in allowed_hosts)


def _is_pdf_host_temp_blocked(host: str) -> bool:
    h = str(host or "").lower().strip()
    if not h:
        return False
    until = float(_PDF_DOMAIN_DENY_CACHE.get(h, 0.0))
    now = time.time()
    if until <= now:
        _PDF_DOMAIN_DENY_CACHE.pop(h, None)
        return False
    return True


def _mark_pdf_host_temp_blocked(host: str, ttl_sec: float) -> None:
    h = str(host or "").lower().strip()
    if not h:
        return
    _PDF_DOMAIN_DENY_CACHE[h] = time.time() + max(0.0, float(ttl_sec))


def _download_pdf_from_url_if_any(
    item: Dict[str, Any],
    *,
    cfg: Dict[str, Any] | None = None,
    papers_dir: str,
    allow_download: bool,
    polite_delay_sec: float,
) -> Dict[str, Any]:
    if item.get("pdf_path") or not allow_download:
        return item
    pdf_url = str(item.get("pdf_url") or "").strip()
    if not pdf_url:
        return item
    only_allowed_hosts, allowed_hosts, ttl_sec = _resolve_pdf_download_policy(cfg)
    host = _pdf_host_from_url(pdf_url)
    if _is_pdf_host_temp_blocked(host):
        logger.debug(
            "Skip PDF download for %s: host %s is temporarily blocked",
            item.get("uid") or item.get("title"),
            host,
        )
        return item
    if only_allowed_hosts and not _is_pdf_host_whitelisted(host, allowed_hosts):
        if item.get("doi") or _extract_doi_from_uid(str(item.get("uid") or "")):
            item["pdf_source"] = item.get("pdf_source") or "metadata_only"
        logger.debug(
            "Skip direct PDF download for %s: host %s not in allowlist",
            item.get("uid") or item.get("title"),
            host or "(none)",
        )
        return item
    try:
        uid = str(item.get("uid") or _canonical_paper_key(item))
        pdf_path = download_pdf(pdf_url, papers_dir, uid, polite_delay_sec=polite_delay_sec)
        item["pdf_path"] = pdf_path
        if "arxiv.org" in host:
            item["pdf_source"] = item.get("pdf_source") or "arxiv"
        elif item.get("doi"):
            item["pdf_source"] = item.get("pdf_source") or "publisher"
        else:
            item["pdf_source"] = item.get("pdf_source") or "openaccess"
    except Exception as e:  # pragma: no cover - network path
        status = getattr(getattr(e, "response", None), "status_code", None)
        if int(status or 0) == 403 and host:
            _mark_pdf_host_temp_blocked(host, ttl_sec)
            logger.warning(
                "PDF download forbidden for host %s; temporarily blocked %.0fs (%s)",
                host,
                ttl_sec,
                item.get("uid") or item.get("title"),
            )
        elif int(status or 0) == 404:
            logger.info("PDF not found for %s: %s", item.get("uid") or item.get("title"), e)
        else:
            logger.warning("PDF download failed for %s: %s", item.get("uid") or item.get("title"), e)
    return item


def _arxiv_match_score(candidate: Dict[str, Any], arxiv_like: Dict[str, Any]) -> float:
    t1 = _norm_text(candidate.get("title", ""))
    t2 = _norm_text(arxiv_like.get("title", ""))
    title_sim = SequenceMatcher(a=t1, b=t2).ratio()
    year1 = _safe_int(candidate.get("year"), 0)
    year2 = _safe_int(arxiv_like.get("year"), 0)
    year_bonus = 0.0
    if year1 > 0 and year2 > 0:
        year_bonus = max(0.0, 1.0 - min(5, abs(year1 - year2)) / 5.0)
    a1 = {x.lower() for x in candidate.get("authors", []) if isinstance(x, str)}
    a2 = {x.lower() for x in arxiv_like.get("authors", []) if isinstance(x, str)}
    author_overlap = len(a1 & a2) / max(1, len(a1)) if a1 else 0.0
    return 0.72 * title_sim + 0.18 * author_overlap + 0.10 * year_bonus


def _venue_first_pdf_fallback(
    item: Dict[str, Any],
    *,
    cfg: Dict[str, Any],
    query: str,
    papers_dir: str,
    sqlite_path: str,
    allow_download: bool,
    polite_delay_sec: float,
    arxiv_enabled: bool,
    arxiv_per_query: int,
) -> Dict[str, Any]:
    # 1) Prefer publisher/open-access PDF if available.
    item = _download_pdf_from_url_if_any(
        item,
        cfg=cfg,
        papers_dir=papers_dir,
        allow_download=allow_download,
        polite_delay_sec=polite_delay_sec,
    )
    if item.get("pdf_path") or item.get("pdf_url"):
        if not item.get("pdf_source"):
            item["pdf_source"] = "openaccess"
        return item

    # 2) Fallback to arXiv nearest match.
    if not arxiv_enabled:
        return item
    fallback_query = str(item.get("doi") or "").strip() or str(item.get("title") or "").strip() or query
    if not fallback_query:
        return item
    try:
        candidates = fetch_arxiv_records(
            query=fallback_query,
            sqlite_path=sqlite_path,
            papers_dir=papers_dir,
            max_results=max(3, min(8, int(arxiv_per_query))),
            download=allow_download,
            download_source=False,
            source_dir=str(ingest_latex_source_dir(Path("."), cfg)),
            polite_delay_sec=polite_delay_sec,
        )
    except Exception as e:  # pragma: no cover - network path
        logger.warning("arXiv fallback fetch failed for '%s': %s", item.get("title"), e)
        return item

    if not candidates:
        return item

    arxiv_candidates = [_paper_from_arxiv_record(r, query=query) for r in candidates]
    scored = sorted(
        arxiv_candidates,
        key=lambda x: _arxiv_match_score(item, x),
        reverse=True,
    )
    best = scored[0]
    if _arxiv_match_score(item, best) < 0.72:
        return item

    merged = _merge_paper(item, best)
    merged["pdf_source"] = "arxiv_fallback"
    # Keep DOI uid if known; otherwise use arXiv uid.
    if not _extract_doi_from_uid(str(merged.get("uid") or "")) and merged.get("doi"):
        merged["uid"] = f"doi:{merged['doi']}"
    elif not merged.get("uid"):
        merged["uid"] = best.get("uid", "")
    return merged



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
        seen_web: set[str] = set()
        # Quality-first academic retrieval:
        # 1) fetch across enabled sources
        # 2) canonical dedupe (DOI > arXiv > title+year)
        # 3) unified rerank with venue diversity
        # 4) venue-first PDF retrieval, then arXiv fallback
        if academic_queries and (
            _source_enabled(cfg, "arxiv")
            or _source_enabled(cfg, "openalex")
            or _source_enabled(cfg, "google_scholar")
            or _source_enabled(cfg, "semantic_scholar")
        ):
            order = _academic_provider_order(cfg)
            query_all = bool(search_provider_cfg.get("query_all_academic", False))

            arxiv_cfg = sources_cfg.get("arxiv", {})
            gs_cfg = sources_cfg.get("google_scholar", {})
            s2_cfg = sources_cfg.get("semantic_scholar", {})
            oa_cfg = sources_cfg.get("openalex", {})

            target_per_query = int(cfg.get("agent", {}).get("papers_per_query", 5))
            arxiv_per_query = int(arxiv_cfg.get("max_results_per_query", target_per_query))
            gs_per_query = int(gs_cfg.get("max_results_per_query", target_per_query))
            s2_per_query = int(s2_cfg.get("max_results_per_query", target_per_query))
            s2_min_interval = float(s2_cfg.get("polite_delay_sec", 1.0))
            s2_max_retries = int(s2_cfg.get("max_retries", 4))
            s2_backoff = float(s2_cfg.get("retry_backoff_sec", 1.5))
            oa_per_query = int(oa_cfg.get("max_results_per_query", target_per_query))
            max_per_venue = int(cfg.get("agent", {}).get("source_ranking", {}).get("max_per_venue", 2))

            papers_dir = str((root / cfg.get("paths", {}).get("papers_dir", "data/papers")).resolve())
            sqlite_path = str(
                (root / cfg.get("metadata_store", {}).get("sqlite_path", "data/metadata/papers.sqlite")).resolve()
            )
            source_dir = str(ingest_latex_source_dir(root, cfg))
            download_source = ingest_latex_download_source(cfg)
            arxiv_enabled = _source_enabled(cfg, "arxiv")
            paper_pool: Dict[str, Dict[str, Any]] = {}

            for q in academic_queries:
                route = query_routes.get(q, {})
                allow_download = bool(route.get("download_pdf", arxiv_cfg.get("download_pdf", True)))
                per_query_candidates: Dict[str, Dict[str, Any]] = {}

                if arxiv_enabled:
                    logger.info("[arXiv] Searching: %s (max %d)", q, arxiv_per_query)
                    try:
                        records = fetch_arxiv_records(
                            query=q,
                            sqlite_path=sqlite_path,
                            papers_dir=papers_dir,
                            max_results=arxiv_per_query,
                            download=allow_download,
                            download_source=download_source,
                            source_dir=source_dir,
                            polite_delay_sec=delay,
                        )
                        for r in records:
                            c = _paper_from_arxiv_record(r, query=q)
                            key = _canonical_paper_key(c)
                            if key in per_query_candidates:
                                per_query_candidates[key] = _merge_paper(per_query_candidates[key], c)
                            else:
                                per_query_candidates[key] = c
                    except Exception as e:  # pragma: no cover - network path
                        logger.error("[arXiv] Failed for '%s': %s", q, e)

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
                        gs_max = max(gs_per_query, need_more)
                        logger.info("[Google Scholar] Searching: %s (max %d)", q, gs_max)
                        try:
                            merged_results.extend(query_google_scholar(q, max_results=gs_max))
                        except Exception as e:  # pragma: no cover - network path
                            logger.error("[Google Scholar] Failed for '%s': %s", q, e)
                    elif provider == "semantic_scholar" and _source_enabled(cfg, "semantic_scholar"):
                        if need_more == 0 and merged_results and not query_all:
                            continue
                        s2_max = max(s2_per_query, need_more)
                        logger.info("[Semantic Scholar] Searching: %s (max %d)", q, s2_max)
                        try:
                            merged_results.extend(
                                query_semantic_scholar(
                                    q,
                                    max_results=s2_max,
                                    min_interval_sec=s2_min_interval,
                                    max_retries=s2_max_retries,
                                    backoff_sec=s2_backoff,
                                )
                            )
                        except Exception as e:  # pragma: no cover - network path
                            logger.error("[Semantic Scholar] Failed for '%s': %s", q, e)

                for r in dedupe_search_results(merged_results):
                    c = _paper_from_search_result(r, query=q)
                    key = _canonical_paper_key(c)
                    if key in per_query_candidates:
                        per_query_candidates[key] = _merge_paper(per_query_candidates[key], c)
                    else:
                        per_query_candidates[key] = c

                per_query_ranked = _rerank_with_diversity(
                    list(per_query_candidates.values()),
                    query=q,
                    top_k=max(target_per_query, oa_per_query, s2_per_query, gs_per_query, arxiv_per_query),
                    max_per_venue=max_per_venue,
                )

                for item in per_query_ranked:
                    item = _venue_first_pdf_fallback(
                        item,
                        cfg=cfg,
                        query=q,
                        papers_dir=papers_dir,
                        sqlite_path=sqlite_path,
                        allow_download=allow_download,
                        polite_delay_sec=delay,
                        arxiv_enabled=arxiv_enabled,
                        arxiv_per_query=arxiv_per_query,
                    )
                    key = _canonical_paper_key(item)
                    if key in paper_pool:
                        merged = _merge_paper(paper_pool[key], item)
                        merged["final_score"] = max(
                            float(paper_pool[key].get("final_score", 0.0)),
                            float(item.get("final_score", 0.0)),
                        )
                        paper_pool[key] = merged
                    else:
                        paper_pool[key] = item

            new_papers = sorted(
                list(paper_pool.values()),
                key=lambda x: float(x.get("final_score", 0.0)),
                reverse=True,
            )

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
