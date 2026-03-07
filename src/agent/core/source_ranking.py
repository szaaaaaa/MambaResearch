"""Source tier classification, deduplication, ranking, and shared text utilities."""
from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urlparse

# ── Shared text constants ────────────────────────────────────────────

_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "are", "can", "what", "how",
    "why", "when", "where", "which", "best", "across", "into", "using", "used", "than",
    "of", "to", "does", "do", "did", "affect", "extent",
    "between", "over", "under", "through", "about", "agentic", "traditional", "systems",
    "system", "study", "survey", "analysis", "framework", "frameworks",
}

_GENERIC_TOPIC_ANCHOR_TERMS = {
    "machine", "learning", "deep", "neural", "model", "models", "method", "methods",
    "approach", "approaches", "framework", "frameworks", "study", "studies", "analysis",
    "application", "applications", "system", "systems", "task", "tasks", "based", "using",
    "research", "paper", "papers", "problem", "problems", "technique", "techniques",
    "concept", "drift", "online", "data",
}

_ACADEMIC_DOMAINS = {
    "arxiv.org",
    "openalex.org",
    "api.openalex.org",
    "aclanthology.org",
    "ieeexplore.ieee.org",
    "openreview.net",
    "dl.acm.org",
    "springer.com",
    "link.springer.com",
    "neurips.cc",
    "jmlr.org",
}

_ENGINEERING_DOMAINS = {
    "developer.nvidia.com",
    "aws.amazon.com",
    "research.ibm.com",
    "cloud.google.com",
    "developers.googleblog.com",
    "learn.microsoft.com",
    "openai.com",
    "anthropic.com",
    "langchain.com",
}

# ── Shared text utilities ────────────────────────────────────────────


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]{2,}", (text or "").lower())


# ── Source URL / UID helpers ─────────────────────────────────────────


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    try:
        netloc = urlparse(url).netloc.lower().strip()
    except Exception:
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _uid_to_resolvable_url(uid: str) -> str:
    u = (uid or "").strip()
    if not u:
        return ""
    low = u.lower()
    if low.startswith("arxiv:"):
        return f"https://arxiv.org/abs/{u.split(':', 1)[1]}"
    if low.startswith("doi:"):
        return f"https://doi.org/{u.split(':', 1)[1]}"
    return ""


def _normalize_source_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    try:
        parsed = urlparse(u)
    except Exception:
        return u
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        path = parsed.path.rstrip("/")
        return f"{parsed.scheme}://{parsed.netloc}{path}"
    return u


# ── Source tier and traceability ─────────────────────────────────────


def _source_tier(a: Dict[str, Any]) -> str:
    uid = str(a.get("uid") or "").lower().strip()
    source = str(a.get("source") or "").lower().strip()
    url = str(a.get("url") or "").strip() or _uid_to_resolvable_url(uid)
    domain = _extract_domain(url)

    if uid.startswith("arxiv:") or uid.startswith("doi:"):
        return "A"
    if domain in _ACADEMIC_DOMAINS:
        return "A"
    if source in {"arxiv", "openalex", "semantic_scholar", "google_scholar"}:
        return "A"
    if domain in _ENGINEERING_DOMAINS:
        return "B"
    return "C"


def _has_traceable_source(a: Dict[str, Any]) -> bool:
    url = str(a.get("url") or "").strip()
    pdf_url = str(a.get("pdf_url") or "").strip()
    pdf_path = str(a.get("pdf_path") or "").strip()
    uid = str(a.get("uid") or "").strip().lower()
    if url:
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return True
    if pdf_url:
        parsed = urlparse(pdf_url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return True
    if pdf_path:
        return True
    return uid.startswith("arxiv:") or uid.startswith("doi:")


# ── Deduplication and ranking ────────────────────────────────────────


def _source_dedupe_key(a: Dict[str, Any]) -> str:
    uid = str(a.get("uid") or "").strip().lower()
    if uid:
        return f"uid:{uid}"
    nurl = _normalize_source_url(str(a.get("url") or ""))
    if nurl:
        return f"url:{nurl}"
    title = re.sub(r"\s+", " ", str(a.get("title") or "").strip().lower())
    return f"title:{title}"


def _dedupe_and_rank_analyses(analyses: List[Dict[str, Any]], max_items: int) -> List[Dict[str, Any]]:
    dedup: Dict[str, Dict[str, Any]] = {}
    for a in analyses:
        x = dict(a)
        if not x.get("url"):
            x["url"] = _uid_to_resolvable_url(str(x.get("uid") or ""))
        key = _source_dedupe_key(x)
        prev = dedup.get(key)
        if prev is None:
            dedup[key] = x
            continue
        prev_score = float(prev.get("relevance_score", 0) or 0)
        cur_score = float(x.get("relevance_score", 0) or 0)
        if cur_score > prev_score:
            dedup[key] = x
    ranked = sorted(
        dedup.values(),
        key=lambda i: (
            float(i.get("relevance_score", 0) or 0),
            1 if str(i.get("source") or "").lower() in {"arxiv", "openalex", "google_scholar", "semantic_scholar"} else 0,
        ),
        reverse=True,
    )
    return ranked[: max(1, int(max_items))]


# ── Topic relevance ─────────────────────────────────────────────────


def _semantic_reference_text(a: Dict[str, Any]) -> str:
    return " ".join(
        [
            str(a.get("title") or ""),
            str(a.get("abstract") or ""),
            str(a.get("summary") or ""),
            str(a.get("snippet") or ""),
            " ".join(a.get("key_findings", []) if isinstance(a.get("key_findings"), list) else []),
        ]
    )


def _rq_overlap_stats(text: str, research_questions: List[str]) -> tuple[int, float]:
    text_tokens = set(_tokenize(text))
    max_hits = 0
    max_ratio = 0.0
    for rq in research_questions:
        rq_tokens = {t for t in _tokenize(rq) if t not in _STOPWORDS}
        if not rq_tokens:
            continue
        hits = len(rq_tokens & text_tokens)
        ratio = hits / max(1, len(rq_tokens))
        if hits > max_hits or (hits == max_hits and ratio > max_ratio):
            max_hits = hits
            max_ratio = ratio
    return max_hits, max_ratio


def _claim_map_evidence_keys(claim_map: List[Dict[str, Any]] | None = None) -> set[str]:
    keys: set[str] = set()
    for claim in claim_map or []:
        evidence_list = claim.get("evidence", []) if isinstance(claim.get("evidence"), list) else []
        for evidence in evidence_list:
            uid = str(evidence.get("uid") or "").strip().lower()
            url = _normalize_source_url(str(evidence.get("url") or ""))
            if uid:
                keys.add(f"uid:{uid}")
            if url:
                keys.add(f"url:{url}")
    return keys


def _semantic_reference_profile(
    analyses: List[Dict[str, Any]],
    *,
    research_questions: List[str],
    claim_map: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    claim_keys = _claim_map_evidence_keys(claim_map)
    profiled: List[Dict[str, Any]] = []
    for analysis in analyses:
        item = dict(analysis)
        dedupe_key = _source_dedupe_key(item)
        overlap_hits, overlap_ratio = _rq_overlap_stats(
            _semantic_reference_text(item),
            research_questions,
        )
        relevance = float(item.get("relevance_score", 0.0) or 0.0)

        if dedupe_key in claim_keys:
            label = "core"
        elif overlap_hits >= 2 and (overlap_ratio >= 0.20 or relevance >= 0.45):
            label = "core"
        elif overlap_hits >= 1:
            label = "background"
        else:
            label = "reject"

        item["semantic_reference_label"] = label
        item["semantic_rq_overlap_hits"] = overlap_hits
        item["semantic_rq_overlap_ratio"] = round(overlap_ratio, 4)
        profiled.append(item)
    return profiled


def _semantic_reference_filter(
    analyses: List[Dict[str, Any]],
    *,
    research_questions: List[str],
    claim_map: List[Dict[str, Any]] | None = None,
    max_background: int = 0,
    max_items: int | None = None,
) -> List[Dict[str, Any]]:
    profiled = _semantic_reference_profile(
        analyses,
        research_questions=research_questions,
        claim_map=claim_map,
    )
    claim_keys = _claim_map_evidence_keys(claim_map)
    selected: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def _push(item: Dict[str, Any]) -> bool:
        key = _source_dedupe_key(item)
        if key in seen:
            return False
        seen.add(key)
        selected.append(item)
        return True

    for item in profiled:
        if _source_dedupe_key(item) in claim_keys and item.get("semantic_reference_label") == "core":
            _push(item)
            if max_items is not None and len(selected) >= max_items:
                return selected[:max_items]

    for item in profiled:
        if item.get("semantic_reference_label") == "core":
            _push(item)
            if max_items is not None and len(selected) >= max_items:
                return selected[:max_items]

    background_added = 0
    for item in profiled:
        if item.get("semantic_reference_label") != "background":
            continue
        if background_added >= max(0, int(max_background)):
            continue
        if _push(item):
            background_added += 1
        if max_items is not None and len(selected) >= max_items:
            break

    return selected[:max_items] if max_items is not None else selected


def _is_topic_relevant(
    *,
    text: str,
    topic_keywords: set[str],
    block_terms: List[str],
    min_hits: int = 1,
    anchor_terms: set[str] | None = None,
    min_anchor_hits: int = 0,
) -> bool:
    lowered = (text or "").lower()
    if any(bt and bt.lower() in lowered for bt in block_terms):
        return False
    token_set = set(_tokenize(lowered))
    hits = len(topic_keywords & token_set)
    if hits < max(1, int(min_hits)):
        return False

    anchors = set(anchor_terms or set())
    if anchors:
        anchor_hits = len(anchors & token_set)
        if anchor_hits < max(1, int(min_anchor_hits)):
            return False
    return True
