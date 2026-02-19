"""Multi-source web fetcher: DuckDuckGo search, page scraping, Semantic Scholar.

All functions are designed to work without extra API keys (unlike Tavily/Serper).
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ResearchAgent/0.2; "
        "+https://github.com/research-agent)"
    ),
}


# ── Data containers ──────────────────────────────────────────────────

@dataclass
class WebResult:
    """A single result returned by a web search engine."""
    uid: str
    title: str
    url: str
    snippet: str
    source: str            # "web", "semantic_scholar", "arxiv"
    body: str = ""         # full extracted text (filled by scrape step)
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    pdf_url: Optional[str] = None
    pdf_path: Optional[str] = None


# ── DuckDuckGo search ────────────────────────────────────────────────

def search_duckduckgo(
    query: str,
    max_results: int = 10,
) -> List[WebResult]:
    """Search the web via DuckDuckGo (no API key needed)."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.error(
            "duckduckgo-search not installed. "
            "Run: pip install duckduckgo-search"
        )
        return []

    results: List[WebResult] = []
    try:
        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=max_results))
        for i, h in enumerate(hits):
            url = h.get("href", h.get("link", ""))
            uid = f"web:{_url_to_uid(url)}" if url else f"web:ddg_{i}"
            results.append(
                WebResult(
                    uid=uid,
                    title=h.get("title", ""),
                    url=url,
                    snippet=h.get("body", ""),
                    source="web",
                )
            )
    except Exception as e:
        logger.error("DuckDuckGo search failed: %s", e)
    return results


# ── Semantic Scholar ─────────────────────────────────────────────────

_S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"

def search_semantic_scholar(
    query: str,
    max_results: int = 10,
) -> List[WebResult]:
    """Search Semantic Scholar for academic papers (free, no key)."""
    results: List[WebResult] = []
    try:
        resp = requests.get(
            _S2_SEARCH,
            params={
                "query": query,
                "limit": min(max_results, 100),
                "fields": "title,authors,year,abstract,externalIds,url,openAccessPdf",
            },
            headers=_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
    except Exception as e:
        logger.error("Semantic Scholar search failed: %s", e)
        return []

    for paper in data:
        paper_id = paper.get("paperId", "")
        ext = paper.get("externalIds") or {}
        arxiv_id = ext.get("ArXiv", "")
        doi = ext.get("DOI", "")

        if arxiv_id:
            uid = f"arxiv:{arxiv_id}"
        elif doi:
            uid = f"doi:{doi}"
        else:
            uid = f"s2:{paper_id}"

        authors = [
            a.get("name", "") for a in (paper.get("authors") or [])
        ]

        pdf_info = paper.get("openAccessPdf") or {}
        pdf_url = pdf_info.get("url")

        results.append(
            WebResult(
                uid=uid,
                title=paper.get("title", ""),
                url=paper.get("url", f"https://www.semanticscholar.org/paper/{paper_id}"),
                snippet=paper.get("abstract", "") or "",
                source="semantic_scholar",
                authors=authors,
                year=paper.get("year"),
                pdf_url=pdf_url,
            )
        )
    return results


# ── Web page scraping ────────────────────────────────────────────────

def fetch_page_content(
    url: str,
    timeout: int = 20,
) -> str:
    """Extract main textual content from a web page.

    Uses trafilatura if available, falls back to basic HTML stripping.
    """
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return ""

    # Try trafilatura first (best quality)
    try:
        import trafilatura
        text = trafilatura.extract(html, include_links=False, include_tables=True)
        if text:
            return text.strip()
    except ImportError:
        pass

    # Fallback: BeautifulSoup
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        # Remove script/style
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Collapse blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:50000]  # cap to avoid huge pages
    except ImportError:
        pass

    # Last resort: regex strip
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:50000]


def scrape_results(
    results: List[WebResult],
    *,
    polite_delay_sec: float = 0.5,
    max_chars: int = 30000,
) -> List[WebResult]:
    """Fetch full body text for each WebResult that has a URL."""
    for r in results:
        if r.body or not r.url:
            continue
        # Skip PDF URLs (these are handled by the PDF pipeline)
        if r.url.lower().endswith(".pdf"):
            continue
        logger.info("Scraping: %s", r.url)
        r.body = fetch_page_content(r.url)[:max_chars]
        if polite_delay_sec > 0:
            time.sleep(polite_delay_sec)
    return results


# ── Helpers ──────────────────────────────────────────────────────────

def _url_to_uid(url: str) -> str:
    """Convert a URL to a filesystem-safe UID fragment."""
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "")
    path = parsed.path.strip("/").replace("/", "_")
    raw = f"{host}_{path}" if path else host
    # keep only alnum, dash, underscore, dot
    return re.sub(r"[^a-zA-Z0-9._-]", "_", raw)[:120]


def dedup_results(
    *result_lists: List[WebResult],
) -> List[WebResult]:
    """Merge multiple result lists, deduplicating by uid."""
    seen: dict[str, WebResult] = {}
    for lst in result_lists:
        for r in lst:
            if r.uid not in seen:
                seen[r.uid] = r
    return list(seen.values())
