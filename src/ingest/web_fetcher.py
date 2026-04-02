from __future__ import annotations

"""多源网页抓取器。

支持：
- Google / Google Scholar（通过 SerpAPI）
- Google CSE
- Bing 网页搜索
- DuckDuckGo
- Semantic Scholar
- OpenAlex
- GitHub 搜索 API
"""

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable, List, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ResearchAgent/0.2; "
        "+https://github.com/research-agent)"
    ),
}

_SERPAPI_URL = "https://serpapi.com/search.json"
_S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
_OPENALEX_WORKS = "https://api.openalex.org/works"
_GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"
_BING_WEB_SEARCH_URL = "https://api.bing.microsoft.com/v7.0/search"
_GITHUB_REPO_SEARCH_URL = "https://api.github.com/search/repositories"
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LIKELY_CN_DOMAINS = {
    "zhihu.com",
    "zhidao.baidu.com",
    "baike.baidu.com",
    "tieba.baidu.com",
    "weibo.com",
    "bilibili.com",
    "csdn.net",
    "juejin.cn",
}
_S2_LOCK = threading.Lock()
_S2_LAST_CALL_TS = 0.0


@dataclass
class WebResult:
    """搜索源返回的单条结果。"""

    uid: str
    title: str
    url: str
    snippet: str
    source: str  # 例如 "web", "google", "google_cse", "bing", "semantic_scholar", "openalex", "github"
    body: str = ""  # 完整提取的文本（由抓取步骤填充）
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    pdf_url: Optional[str] = None
    pdf_path: Optional[str] = None
    doi: str = ""
    arxiv_id: str = ""
    venue: str = ""
    journal: str = ""
    citation_count: int = 0
    peer_reviewed: bool = False
    source_origins: List[str] = field(default_factory=list)


def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _is_chinese_result(r: WebResult) -> bool:
    host = urlparse(r.url or "").netloc.lower()
    if host.endswith(".cn") or any(host.endswith(x) for x in _LIKELY_CN_DOMAINS):
        return True
    return _contains_cjk(f"{r.title} {r.snippet}")


def _url_to_uid(url: str) -> str:
    """将 URL 转换为文件系统安全的 UID 片段。"""
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "")
    path = parsed.path.strip("/").replace("/", "_")
    raw = f"{host}_{path}" if path else host
    return re.sub(r"[^a-zA-Z0-9._-]", "_", raw)[:120]


def _respect_semantic_scholar_rate_limit(min_interval_sec: float) -> None:
    """本进程中 Semantic Scholar API 调用的全局限流。"""
    global _S2_LAST_CALL_TS
    wait = 0.0
    now = time.monotonic()
    with _S2_LOCK:
        elapsed = now - _S2_LAST_CALL_TS
        if elapsed < max(0.0, float(min_interval_sec)):
            wait = float(min_interval_sec) - elapsed
        if wait > 0:
            _S2_LAST_CALL_TS = now + wait
        else:
            _S2_LAST_CALL_TS = now
    if wait > 0:
        time.sleep(wait)


def dedup_results(*result_lists: List[WebResult]) -> List[WebResult]:
    """合并多个结果列表，按 uid 去重。"""
    seen: dict[str, WebResult] = {}
    for lst in result_lists:
        for r in lst:
            if r.uid not in seen:
                seen[r.uid] = r
    return list(seen.values())


def filter_results_by_domain(
    results: List[WebResult],
    *,
    blocked_domains: Iterable[str] | None = None,
) -> List[WebResult]:
    blocked = {d.strip().lower() for d in (blocked_domains or []) if d and d.strip()}
    if not blocked:
        return results

    out: List[WebResult] = []
    for r in results:
        host = urlparse(r.url or "").netloc.lower()
        if any(host == d or host.endswith(f".{d}") for d in blocked):
            continue
        out.append(r)
    return out


def prioritize_results(
    results: List[WebResult],
    *,
    max_results: int,
    prefer_english: bool = True,
    max_chinese_ratio: float = 0.25,
) -> List[WebResult]:
    """优先英文/国际来源，其次中文来源。"""
    uniq = dedup_results(results)
    if not prefer_english:
        return uniq[:max_results]

    en_like: List[WebResult] = []
    zh_like: List[WebResult] = []
    for r in uniq:
        if _is_chinese_result(r):
            zh_like.append(r)
        else:
            en_like.append(r)

    zh_cap = max(0, int(max_results * max(0.0, min(max_chinese_ratio, 1.0))))

    out: List[WebResult] = en_like[:max_results]
    if len(out) < max_results:
        out.extend(zh_like[: max_results - len(out)])
    elif zh_cap > 0:
        keep_en = max_results - zh_cap
        out = en_like[:keep_en] + zh_like[:zh_cap]
    return out[:max_results]


def _search_serpapi(
    query: str,
    *,
    engine: str,
    max_results: int = 10,
    hl: str = "en",
    gl: str = "us",
) -> List[dict]:
    key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not key:
        return []
    try:
        resp = requests.get(
            _SERPAPI_URL,
            params={
                "api_key": key,
                "engine": engine,
                "q": query,
                "num": min(max_results, 20),
                "hl": hl,
                "gl": gl,
            },
            headers=_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        return (resp.json() or {}).get("organic_results", []) or []
    except Exception as e:
        logger.error("SerpAPI search failed (engine=%s): %s", engine, e)
        return []


def search_google(
    query: str,
    max_results: int = 10,
    *,
    hl: str = "en",
    gl: str = "us",
) -> List[WebResult]:
    """当设置了 `SERPAPI_API_KEY` 时通过 SerpAPI 搜索 Google。"""
    rows = _search_serpapi(query, engine="google", max_results=max_results, hl=hl, gl=gl)
    out: List[WebResult] = []
    for i, row in enumerate(rows):
        url = row.get("link", "")
        uid = f"web:{_url_to_uid(url)}" if url else f"web:google_{i}"
        out.append(
            WebResult(
                uid=uid,
                title=row.get("title", ""),
                url=url,
                snippet=row.get("snippet", "") or "",
                source="google",
            )
        )
    return out


def search_google_scholar(
    query: str,
    max_results: int = 10,
) -> List[WebResult]:
    """当设置了 `SERPAPI_API_KEY` 时通过 SerpAPI 搜索 Google Scholar。"""
    rows = _search_serpapi(query, engine="google_scholar", max_results=max_results, hl="en", gl="us")
    out: List[WebResult] = []
    for i, row in enumerate(rows):
        url = row.get("link", "") or row.get("resources", [{}])[0].get("link", "")
        result_id = row.get("result_id", "")
        uid = f"gs:{result_id}" if result_id else (f"web:{_url_to_uid(url)}" if url else f"gs:{i}")
        pub_info = row.get("publication_info", {}) or {}
        summary = pub_info.get("summary", "") or ""
        authors = [a.get("name", "") for a in pub_info.get("authors", []) if a.get("name")]
        year_match = re.search(r"(19|20)\d{2}", summary)
        year = int(year_match.group(0)) if year_match else None
        out.append(
            WebResult(
                uid=uid,
                title=row.get("title", ""),
                url=url,
                snippet=row.get("snippet", "") or summary,
                source="google_scholar",
                authors=authors,
                year=year,
            )
        )
    return out


def search_google_cse(
    query: str,
    max_results: int = 10,
    *,
    hl: str = "en",
    gl: str = "us",
) -> List[WebResult]:
    """搜索 Google 可编程搜索引擎（Custom Search JSON API）。"""
    api_key = os.getenv("GOOGLE_CSE_API_KEY", "").strip()
    cx = os.getenv("GOOGLE_CSE_CX", "").strip()
    if not api_key or not cx:
        return []

    out: List[WebResult] = []
    start = 1
    while len(out) < max_results and start <= 91:
        want = min(10, max_results - len(out))
        try:
            resp = requests.get(
                _GOOGLE_CSE_URL,
                params={
                    "key": api_key,
                    "cx": cx,
                    "q": query,
                    "num": want,
                    "start": start,
                    "hl": hl,
                    "gl": gl,
                },
                headers=_HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            items = (resp.json() or {}).get("items", []) or []
        except Exception as e:
            logger.error("Google CSE search failed: %s", e)
            break

        if not items:
            break
        for row in items:
            url = row.get("link", "")
            uid = f"web:{_url_to_uid(url)}" if url else f"web:google_cse_{len(out)}"
            out.append(
                WebResult(
                    uid=uid,
                    title=row.get("title", ""),
                    url=url,
                    snippet=row.get("snippet", "") or "",
                    source="google_cse",
                )
            )
            if len(out) >= max_results:
                break
        start += len(items)
    return out[:max_results]


def search_bing(
    query: str,
    max_results: int = 10,
    *,
    mkt: str = "en-US",
) -> List[WebResult]:
    """搜索 Bing 网页搜索 API。"""
    api_key = os.getenv("BING_API_KEY", "").strip()
    if not api_key:
        return []

    out: List[WebResult] = []
    offset = 0
    while len(out) < max_results:
        want = min(50, max_results - len(out))
        try:
            resp = requests.get(
                _BING_WEB_SEARCH_URL,
                params={"q": query, "count": want, "offset": offset, "mkt": mkt},
                headers={**_HEADERS, "Ocp-Apim-Subscription-Key": api_key},
                timeout=30,
            )
            resp.raise_for_status()
            rows = (((resp.json() or {}).get("webPages") or {}).get("value") or [])
        except Exception as e:
            logger.error("Bing search failed: %s", e)
            break

        if not rows:
            break
        for row in rows:
            url = row.get("url", "")
            uid = f"web:{_url_to_uid(url)}" if url else f"web:bing_{len(out)}"
            out.append(
                WebResult(
                    uid=uid,
                    title=row.get("name", ""),
                    url=url,
                    snippet=row.get("snippet", "") or "",
                    source="bing",
                )
            )
            if len(out) >= max_results:
                break
        offset += len(rows)
    return out[:max_results]


def search_duckduckgo(
    query: str,
    max_results: int = 10,
    *,
    region: str = "us-en",
) -> List[WebResult]:
    """通过 DuckDuckGo 搜索网页（无需 API 密钥）。"""
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
            hits = list(ddgs.text(query, region=region, max_results=max_results))
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


def search_openalex(
    query: str,
    max_results: int = 10,
) -> List[WebResult]:
    """搜索 OpenAlex 论文 API（免费）。"""
    results: List[WebResult] = []
    try:
        resp = requests.get(
            _OPENALEX_WORKS,
            params={
                "search": query,
                "per-page": min(max_results, 200),
                "select": (
                    "id,doi,title,display_name,publication_year,abstract_inverted_index,"
                    "authorships,primary_location,best_oa_location,ids,cited_by_count,"
                    "type"
                ),
            },
            headers=_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        data = (resp.json() or {}).get("results", []) or []
    except Exception as e:
        logger.error("OpenAlex search failed: %s", e)
        return results

    for row in data:
        title = row.get("display_name") or row.get("title") or ""
        ids = row.get("ids") or {}
        doi_url = ids.get("doi") or row.get("doi") or ""
        arxiv_url = ids.get("arxiv") or ""
        openalex_id = row.get("id", "")
        doi = ""
        if isinstance(doi_url, str) and doi_url:
            doi = (
                doi_url.replace("https://doi.org/", "")
                .replace("http://doi.org/", "")
                .strip()
            )
        arxiv_id = ""
        if isinstance(arxiv_url, str) and arxiv_url:
            arxiv_id = arxiv_url.rsplit("/", 1)[-1].strip()
        uid = ""
        if doi:
            uid = f"doi:{doi.lower()}"
        elif arxiv_id:
            uid = f"arxiv:{arxiv_id.lower()}"
        elif isinstance(openalex_id, str) and openalex_id:
            uid = f"openalex:{openalex_id.rsplit('/', 1)[-1]}"
        else:
            uid = f"openalex:{len(results)}"

        authors = []
        for a in row.get("authorships") or []:
            nm = ((a.get("author") or {}).get("display_name") or "").strip()
            if nm:
                authors.append(nm)

        url = ""
        pdf_url = ""
        venue = ""
        journal = ""
        peer_reviewed = False
        primary = row.get("primary_location") or {}
        best_oa = row.get("best_oa_location") or {}
        landing = primary.get("landing_page_url")
        primary_source = primary.get("source") or {}
        venue = (
            (primary_source.get("display_name") or "").strip()
        )
        source_type = (primary_source.get("type") or "").strip().lower()
        if source_type in {"journal", "conference"}:
            peer_reviewed = True
        if source_type == "journal":
            journal = venue
        pdf_url = (
            (best_oa.get("pdf_url") or "")
            or (primary.get("pdf_url") or "")
        )
        if isinstance(landing, str) and landing:
            url = landing
        elif isinstance(doi_url, str) and doi_url:
            url = doi_url
        elif isinstance(openalex_id, str):
            url = openalex_id

        results.append(
            WebResult(
                uid=uid,
                title=title,
                url=url,
                snippet="",
                source="openalex",
                authors=authors,
                year=row.get("publication_year"),
                pdf_url=pdf_url or None,
                doi=doi.lower(),
                arxiv_id=arxiv_id.lower(),
                venue=venue,
                journal=journal,
                citation_count=int(row.get("cited_by_count") or 0),
                peer_reviewed=peer_reviewed,
                source_origins=["openalex"],
            )
        )
        if len(results) >= max_results:
            break
    return results


def search_semantic_scholar(
    query: str,
    max_results: int = 10,
    *,
    min_interval_sec: float = 1.0,
    max_retries: int = 4,
    backoff_sec: float = 1.5,
) -> List[WebResult]:
    """搜索 Semantic Scholar 学术论文（免费，无需密钥）。"""
    results: List[WebResult] = []
    params = {
        "query": query,
        "limit": min(max_results, 100),
        "fields": (
            "title,authors,year,abstract,externalIds,url,openAccessPdf,"
            "citationCount,venue,journal,publicationTypes"
        ),
    }
    data = []
    for attempt in range(max(1, int(max_retries)) + 1):
        try:
            _respect_semantic_scholar_rate_limit(min_interval_sec=min_interval_sec)
            resp = requests.get(
                _S2_SEARCH,
                params=params,
                headers=_HEADERS,
                timeout=30,
            )
            status = int(resp.status_code)
            if status == 429 or status >= 500:
                if attempt < int(max_retries):
                    sleep_for = max(0.1, float(backoff_sec)) * (2 ** attempt)
                    logger.warning(
                        "Semantic Scholar throttled/server error (status=%s). "
                        "Retrying in %.1fs (attempt %d/%d)",
                        status,
                        sleep_for,
                        attempt + 1,
                        int(max_retries) + 1,
                    )
                    time.sleep(sleep_for)
                    continue
            resp.raise_for_status()
            data = (resp.json() or {}).get("data", []) or []
            break
        except Exception as e:
            if attempt < int(max_retries):
                sleep_for = max(0.1, float(backoff_sec)) * (2 ** attempt)
                logger.warning(
                    "Semantic Scholar request failed (%s). Retrying in %.1fs (attempt %d/%d)",
                    e,
                    sleep_for,
                    attempt + 1,
                    int(max_retries) + 1,
                )
                time.sleep(sleep_for)
                continue
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

        authors = [a.get("name", "") for a in (paper.get("authors") or [])]
        pdf_info = paper.get("openAccessPdf") or {}
        pdf_url = pdf_info.get("url")
        venue = (paper.get("venue") or "").strip()
        journal_info = paper.get("journal") or {}
        journal = (journal_info.get("name") or "").strip()
        pub_types = [str(x).lower() for x in (paper.get("publicationTypes") or []) if x]
        peer_reviewed = bool(journal or venue) and any(
            t in {"journalarticle", "conference", "conferencepaper"} for t in pub_types
        )

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
                doi=str(doi or "").lower(),
                arxiv_id=str(arxiv_id or "").lower(),
                venue=venue,
                journal=journal,
                citation_count=int(paper.get("citationCount") or 0),
                peer_reviewed=peer_reviewed,
                source_origins=["semantic_scholar"],
            )
        )
    return results


def search_github(
    query: str,
    max_results: int = 10,
    *,
    sort: str = "stars",
) -> List[WebResult]:
    """搜索 GitHub 仓库作为网络/工程证据。"""
    token = os.getenv("GITHUB_TOKEN", "").strip()
    headers = dict(_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    results: List[WebResult] = []
    page = 1
    per_page = min(100, max(1, max_results))

    while len(results) < max_results:
        want = min(per_page, max_results - len(results))
        try:
            resp = requests.get(
                _GITHUB_REPO_SEARCH_URL,
                params={
                    "q": query,
                    "sort": sort,
                    "order": "desc",
                    "per_page": want,
                    "page": page,
                },
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            rows = (resp.json() or {}).get("items", []) or []
        except Exception as e:
            logger.error("GitHub search failed: %s", e)
            break

        if not rows:
            break
        for row in rows:
            url = row.get("html_url", "")
            full_name = row.get("full_name", "")
            uid = f"github:{full_name.lower()}" if full_name else f"web:{_url_to_uid(url)}"
            stars = row.get("stargazers_count", 0)
            lang = row.get("language") or ""
            desc = row.get("description") or ""
            snippet = f"stars={stars}; language={lang}; {desc}".strip()
            results.append(
                WebResult(
                    uid=uid,
                    title=full_name or row.get("name", ""),
                    url=url,
                    snippet=snippet,
                    source="github",
                )
            )
            if len(results) >= max_results:
                break
        page += 1
    return results[:max_results]


def fetch_page_content(
    url: str,
    timeout: int = 20,
) -> str:
    """从网页中提取主要文本内容。"""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return ""

    try:
        import trafilatura

        text = trafilatura.extract(html, include_links=False, include_tables=True)
        if text:
            return text.strip()
    except ImportError:
        pass

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:50000]
    except ImportError:
        pass

    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:50000]


def scrape_results(
    results: List[WebResult],
    *,
    polite_delay_sec: float = 0.5,
    max_chars: int = 30000,
) -> List[WebResult]:
    """为每个有 URL 的 WebResult 抓取完整正文文本。"""
    for r in results:
        if r.body or not r.url:
            continue
        if r.url.lower().endswith(".pdf"):
            continue
        logger.info("Scraping: %s", r.url)
        r.body = fetch_page_content(r.url)[:max_chars]
        if polite_delay_sec > 0:
            time.sleep(polite_delay_sec)
    return results
