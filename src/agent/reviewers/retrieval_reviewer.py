"""Retrieval Reviewer – first reviewer gate in the pipeline.

Checks the fetched sources for:
1. Source diversity (academic vs web, unique venues/domains)
2. Year coverage (recency, spread)
3. Venue coverage (are we over-relying on one venue?)
4. Missing topic coverage (any RQ without matching sources?)
5. Suggests supplemental queries when gaps are found

This reviewer is mostly deterministic.  It does NOT call an LLM.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Dict, List, Set
from urllib.parse import urlparse

from src.agent.core.schemas import (
    ResearchState,
    RetrievalReview,
    ReviewerVerdict,
    SourceDiversityStats,
)
from src.agent.core.source_ranking import (
    _ACADEMIC_DOMAINS,
    _STOPWORDS,
    _extract_domain,
    _semantic_reference_profile,
    _source_tier,
    _tokenize,
)
from src.agent.core.state_access import sget, to_namespaced_update

logger = logging.getLogger(__name__)

# ── Thresholds (can be overridden via cfg["reviewer"]["retrieval"]) ───

_DEFAULT_MIN_SOURCES = 5
_DEFAULT_MIN_ACADEMIC_RATIO = 0.4
_DEFAULT_MIN_UNIQUE_VENUES = 2
_DEFAULT_MAX_SINGLE_VENUE_RATIO = 0.6
_DEFAULT_MIN_YEAR_SPREAD = 2
_DEFAULT_RECENT_YEAR_WINDOW = 3  # at least one source within last N years
_DEFAULT_MIN_SEMANTIC_PURITY_RATIO = 0.5
_DEFAULT_MAX_BACKGROUND_RATIO = 0.5
_DEFAULT_MAX_REJECT_RATIO = 0.25


def _extract_year(paper: Dict[str, Any]) -> int | None:
    y = paper.get("year")
    if isinstance(y, int) and 1900 < y < 2100:
        return y
    for field in ("title", "uid", "url"):
        val = str(paper.get(field) or "")
        m = re.search(r"(19|20)\d{2}", val)
        if m:
            candidate = int(m.group())
            if 1900 < candidate < 2100:
                return candidate
    return None


def _extract_venue(paper: Dict[str, Any]) -> str:
    for field in ("venue", "journal", "source"):
        v = str(paper.get(field) or "").strip()
        if v and v.lower() not in {"arxiv", "web", "unknown", ""}:
            return v
    return ""


def _rq_tokens(rq: str) -> Set[str]:
    return {t for t in _tokenize(rq) if t not in _STOPWORDS and len(t) > 2}


def _source_covers_rq(source: Dict[str, Any], rq_toks: Set[str], min_overlap: int = 2) -> bool:
    text = " ".join([
        str(source.get("title") or ""),
        str(source.get("abstract") or ""),
        str(source.get("summary") or ""),
        str(source.get("snippet") or ""),
        " ".join(source.get("key_findings", []) if isinstance(source.get("key_findings"), list) else []),
    ])
    src_toks = set(_tokenize(text))
    return len(rq_toks & src_toks) >= min_overlap


def _compute_diversity(
    papers: List[Dict[str, Any]],
    web_sources: List[Dict[str, Any]],
    current_year: int,
) -> SourceDiversityStats:
    all_sources = list(papers) + list(web_sources)
    venues: List[str] = []
    domains: List[str] = []
    years: List[int] = []

    for s in all_sources:
        v = _extract_venue(s)
        if v:
            venues.append(v)
        url = str(s.get("url") or "")
        d = _extract_domain(url)
        if d:
            domains.append(d)
        y = _extract_year(s)
        if y:
            years.append(y)

    year_dist: Dict[str, int] = {}
    for y in years:
        year_dist[str(y)] = year_dist.get(str(y), 0) + 1

    return SourceDiversityStats(
        total_sources=len(all_sources),
        academic_count=len(papers),
        web_count=len(web_sources),
        unique_venues=sorted(set(venues)),
        unique_domains=sorted(set(domains)),
        year_range=[min(years), max(years)] if years else [],
        year_distribution=year_dist,
    )


def review_retrieval(state: ResearchState) -> Dict[str, Any]:
    """Run the retrieval reviewer gate.

    Reads: papers, web_sources, analyses, research_questions, search_queries
    Writes: review.retrieval_review, review.reviewer_log (appends)
    """
    cfg = state.get("_cfg", {})
    reviewer_cfg = cfg.get("reviewer", {}).get("retrieval", {})

    papers: List[Dict[str, Any]] = list(sget(state, "papers", []))
    web_sources: List[Dict[str, Any]] = list(sget(state, "web_sources", []))
    analyses: List[Dict[str, Any]] = list(sget(state, "analyses", []))
    rqs: List[str] = list(sget(state, "research_questions", []))
    existing_queries: List[str] = list(sget(state, "search_queries", []))

    min_sources = int(reviewer_cfg.get("min_sources", _DEFAULT_MIN_SOURCES))
    min_academic_ratio = float(reviewer_cfg.get("min_academic_ratio", _DEFAULT_MIN_ACADEMIC_RATIO))
    min_unique_venues = int(reviewer_cfg.get("min_unique_venues", _DEFAULT_MIN_UNIQUE_VENUES))
    max_single_venue_ratio = float(reviewer_cfg.get("max_single_venue_ratio", _DEFAULT_MAX_SINGLE_VENUE_RATIO))
    min_year_spread = int(reviewer_cfg.get("min_year_spread", _DEFAULT_MIN_YEAR_SPREAD))
    recent_window = int(reviewer_cfg.get("recent_year_window", _DEFAULT_RECENT_YEAR_WINDOW))
    min_semantic_purity_ratio = float(
        reviewer_cfg.get("min_semantic_purity_ratio", _DEFAULT_MIN_SEMANTIC_PURITY_RATIO)
    )
    max_background_ratio = float(reviewer_cfg.get("max_background_ratio", _DEFAULT_MAX_BACKGROUND_RATIO))
    max_reject_ratio = float(reviewer_cfg.get("max_reject_ratio", _DEFAULT_MAX_REJECT_RATIO))

    import datetime
    current_year = datetime.datetime.now().year

    # ── 1. Diversity stats ────────────────────────────────────────────
    diversity = _compute_diversity(papers, web_sources, current_year)
    total = diversity["total_sources"]

    issues: List[str] = []
    suggested_queries: List[str] = []
    suggested_fixes: List[str] = []

    # ── 2. Source count check ─────────────────────────────────────────
    if total < min_sources:
        issues.append(f"Only {total} sources fetched (minimum: {min_sources})")
        suggested_fixes.append("Broaden search queries or enable additional source backends")

    # ── 3. Academic ratio check ───────────────────────────────────────
    academic_ratio = diversity["academic_count"] / max(1, total)
    if academic_ratio < min_academic_ratio and total >= 3:
        issues.append(
            f"Academic source ratio {academic_ratio:.0%} below threshold {min_academic_ratio:.0%}"
        )
        suggested_fixes.append("Add more academic search queries")

    # ── 4. Venue diversity check ──────────────────────────────────────
    unique_venues = diversity.get("unique_venues", [])
    year_coverage_gaps: List[str] = []
    venue_coverage_gaps: List[str] = []

    if len(unique_venues) < min_unique_venues and total >= 3:
        venue_coverage_gaps.append(
            f"Only {len(unique_venues)} unique venues (minimum: {min_unique_venues})"
        )
        issues.append(venue_coverage_gaps[-1])

    # Check single-venue concentration
    if unique_venues:
        all_venues = []
        for s in list(papers) + list(web_sources):
            v = _extract_venue(s)
            if v:
                all_venues.append(v)
        if all_venues:
            venue_counts = Counter(all_venues)
            top_venue, top_count = venue_counts.most_common(1)[0]
            ratio = top_count / max(1, len(all_venues))
            if ratio > max_single_venue_ratio:
                venue_coverage_gaps.append(
                    f"Venue '{top_venue}' dominates at {ratio:.0%} (max allowed: {max_single_venue_ratio:.0%})"
                )
                issues.append(venue_coverage_gaps[-1])

    # ── 5. Year coverage check ────────────────────────────────────────
    year_range = diversity.get("year_range", [])
    if year_range and len(year_range) == 2:
        spread = year_range[1] - year_range[0]
        if spread < min_year_spread and total >= 3:
            year_coverage_gaps.append(
                f"Year spread is only {spread} years ({year_range[0]}-{year_range[1]}); "
                f"minimum: {min_year_spread}"
            )
            issues.append(year_coverage_gaps[-1])

        # Recency check
        year_dist = diversity.get("year_distribution", {})
        recent_count = sum(
            v for k, v in year_dist.items()
            if k.isdigit() and int(k) >= current_year - recent_window
        )
        if recent_count == 0 and total >= 3:
            year_coverage_gaps.append(
                f"No sources from the last {recent_window} years ({current_year - recent_window}-{current_year})"
            )
            issues.append(year_coverage_gaps[-1])
            suggested_queries.append(f"recent {current_year} survey")
    elif total > 0:
        year_coverage_gaps.append("Unable to extract year information from any source")

    # ── 6. RQ coverage check ──────────────────────────────────────────
    missing_topics: List[str] = []
    all_sources = list(papers) + list(web_sources) + list(analyses)
    for rq in rqs:
        toks = _rq_tokens(rq)
        if not toks:
            continue
        covered = any(_source_covers_rq(s, toks) for s in all_sources)
        if not covered:
            short_rq = rq[:80] + "..." if len(rq) > 80 else rq
            missing_topics.append(short_rq)
            # Generate a supplemental query from uncovered RQ
            key_terms = sorted(toks, key=lambda t: len(t), reverse=True)[:4]
            suggested_queries.append(" ".join(key_terms))
            issues.append(f"No source covers RQ: {short_rq}")

    # ── 7. Tier distribution check ────────────────────────────────────
    tier_counts = Counter(_source_tier(a) for a in analyses) if analyses else Counter()
    if analyses and tier_counts.get("A", 0) == 0:
        issues.append("No tier-A (academic) sources in analyses")
        suggested_fixes.append("Prioritize arxiv/openalex queries for tier-A coverage")

    # ── 8. Determine verdict ──────────────────────────────────────────
    semantic_profile = _semantic_reference_profile(
        analyses,
        research_questions=rqs,
        claim_map=list(sget(state, "claim_evidence_map", [])),
    ) if analyses else []
    semantic_counts = Counter(str(item.get("semantic_reference_label") or "reject") for item in semantic_profile)
    semantic_total = max(1, len(semantic_profile))
    semantic_purity_ratio = semantic_counts.get("core", 0) / semantic_total if semantic_profile else 0.0
    background_ratio = semantic_counts.get("background", 0) / semantic_total if semantic_profile else 0.0
    reject_ratio = semantic_counts.get("reject", 0) / semantic_total if semantic_profile else 0.0
    diversity["semantic_purity_ratio"] = round(semantic_purity_ratio, 4)
    diversity["background_ratio"] = round(background_ratio, 4)
    diversity["reject_ratio"] = round(reject_ratio, 4)
    diversity["semantic_core_count"] = semantic_counts.get("core", 0)
    diversity["semantic_background_count"] = semantic_counts.get("background", 0)
    diversity["semantic_reject_count"] = semantic_counts.get("reject", 0)

    if len(semantic_profile) >= 3:
        if semantic_purity_ratio < min_semantic_purity_ratio:
            issues.append(
                f"Semantic purity ratio {semantic_purity_ratio:.0%} below threshold {min_semantic_purity_ratio:.0%}"
            )
            suggested_fixes.append("Tighten retrieval to sources that directly answer the research questions")
        if background_ratio > max_background_ratio:
            issues.append(
                f"Background ratio {background_ratio:.0%} above threshold {max_background_ratio:.0%}"
            )
            suggested_fixes.append("Reduce background-only sources in the ranked analysis set")
        if reject_ratio > max_reject_ratio:
            issues.append(
                f"Reject ratio {reject_ratio:.0%} above threshold {max_reject_ratio:.0%}"
            )
            suggested_fixes.append("Remove off-topic or weakly related sources before reporting")

    suggested_fixes = list(dict.fromkeys(suggested_fixes))
    critical_issues = sum(
        1
        for i in issues
        if "No source covers RQ" in i or "Only" in i or "Reject ratio" in i
    )

    if not issues:
        status = "pass"
        action = "continue"
        confidence = 0.95
    elif critical_issues >= 2 or len(issues) >= 4:
        status = "fail"
        action = "retry_upstream"
        confidence = 0.7
    else:
        status = "warn"
        action = "continue"
        confidence = 0.8

    verdict = ReviewerVerdict(
        reviewer="retrieval_reviewer",
        status=status,
        action=action,
        issues=issues,
        suggested_fix=suggested_fixes,
        confidence=confidence,
    )

    retrieval_review = RetrievalReview(
        verdict=verdict,
        diversity_stats=diversity,
        missing_key_topics=missing_topics,
        year_coverage_gaps=year_coverage_gaps,
        venue_coverage_gaps=venue_coverage_gaps,
        suggested_queries=suggested_queries,
    )

    # Log summary
    logger.info(
        "[RetrievalReviewer] status=%s action=%s issues=%d suggested_queries=%d",
        status, action, len(issues), len(suggested_queries),
    )
    for issue in issues:
        logger.info("[RetrievalReviewer]   - %s", issue)

    # Build state update
    existing_log = list(sget(state, "reviewer_log", []))
    existing_log.append(dict(verdict))

    update: Dict[str, Any] = {
        "review": {
            "retrieval_review": dict(retrieval_review),
            "reviewer_log": existing_log,
        },
        "status": f"Retrieval review: {status} ({len(issues)} issues)",
    }

    # When retrying, inject suggested queries and bump retry counter
    if action == "retry_upstream" and suggested_queries:
        merged_queries = list(dict.fromkeys(existing_queries + suggested_queries))
        update["search_queries"] = merged_queries
        update["_academic_queries"] = merged_queries
        update["_web_queries"] = merged_queries
        logger.info(
            "[RetrievalReviewer] Injecting %d supplemental queries for retry",
            len(suggested_queries),
        )

    retries = state.get("_retrieval_review_retries", 0)
    update["_retrieval_review_retries"] = retries + 1

    return to_namespaced_update(update)
