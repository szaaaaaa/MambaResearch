"""Citation Validator – deterministic metadata validation for references.

Two-layer design per update.md §7.4:
1. Deterministic metadata validator (DOI format, year range, author presence, venue, URL)
2. Cross-check against claim_evidence_map for orphaned/phantom references

This does NOT call an LLM.  All checks are rule-based.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List
from urllib.parse import urlparse

from src.agent.core.reference_utils import extract_reference_urls
from src.agent.core.schemas import (
    CitationValidationEntry,
    CitationValidationReport,
    ResearchState,
    ReviewerVerdict,
)
from src.agent.core.source_ranking import _extract_domain, _uid_to_resolvable_url
from src.agent.core.state_access import sget, to_namespaced_update

logger = logging.getLogger(__name__)

_DOI_RE = re.compile(r"^10\.\d{4,}/\S+$")
_ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")


def _validate_uid(uid: str) -> List[str]:
    """Check that a uid has a recognizable format."""
    issues: List[str] = []
    u = (uid or "").strip()
    if not u:
        issues.append("missing_uid")
        return issues
    low = u.lower()
    if low.startswith("arxiv:"):
        arxiv_part = u.split(":", 1)[1].strip()
        if not _ARXIV_ID_RE.match(arxiv_part):
            issues.append(f"malformed_arxiv_id: {arxiv_part}")
    elif low.startswith("doi:"):
        doi_part = u.split(":", 1)[1].strip()
        if not _DOI_RE.match(doi_part):
            issues.append(f"malformed_doi: {doi_part}")
    return issues


def _validate_year(year: Any) -> tuple[bool, List[str]]:
    """Check year is a plausible publication year."""
    if year is None:
        return False, ["missing_year"]
    try:
        y = int(year)
    except (TypeError, ValueError):
        return False, [f"invalid_year_format: {year}"]
    if y < 1900 or y > 2030:
        return False, [f"year_out_of_range: {y}"]
    return True, []


def _validate_authors(authors: Any) -> tuple[bool, List[str]]:
    """Check author list is present and non-empty."""
    if not authors:
        return False, ["missing_authors"]
    if isinstance(authors, list):
        if not authors or all(not str(a).strip() for a in authors):
            return False, ["empty_author_list"]
        return True, []
    if isinstance(authors, str) and authors.strip():
        return True, []
    return False, ["invalid_author_format"]


def _validate_url(url: str) -> tuple[bool, List[str]]:
    """Check URL is syntactically valid."""
    u = (url or "").strip()
    if not u:
        return False, ["missing_url"]
    try:
        parsed = urlparse(u)
        if parsed.scheme not in {"http", "https"}:
            return False, [f"non_http_url: {u[:60]}"]
        if not parsed.netloc:
            return False, [f"no_netloc: {u[:60]}"]
    except Exception:
        return False, [f"unparseable_url: {u[:60]}"]
    return True, []


def _validate_venue(venue: str, source: str) -> tuple[bool, List[str]]:
    """Check venue is present (except for arxiv/web where it may be absent)."""
    v = (venue or "").strip()
    s = (source or "").strip().lower()
    if not v and s not in {"arxiv", "web", "unknown", ""}:
        return False, ["missing_venue"]
    return True, []


def _validate_single_analysis(a: Dict[str, Any]) -> CitationValidationEntry:
    """Run all metadata checks on a single analysis/source entry."""
    uid = str(a.get("uid") or "")
    url = str(a.get("url") or "").strip() or _uid_to_resolvable_url(uid)
    source = str(a.get("source") or "")
    venue = str(a.get("venue") or a.get("journal") or "")
    year = a.get("year")
    authors = a.get("authors")

    all_issues: List[str] = []

    # UID check
    all_issues.extend(_validate_uid(uid))

    # Year check
    year_valid, year_issues = _validate_year(year)
    all_issues.extend(year_issues)

    # Author check
    author_valid, author_issues = _validate_authors(authors)
    all_issues.extend(author_issues)

    # URL check
    url_valid, url_issues = _validate_url(url)
    all_issues.extend(url_issues)

    # Venue check
    venue_valid, venue_issues = _validate_venue(venue, source)
    all_issues.extend(venue_issues)

    # DOI format check (if uid is a DOI)
    doi_valid = True
    if uid.lower().startswith("doi:"):
        doi_part = uid.split(":", 1)[1].strip()
        if not _DOI_RE.match(doi_part):
            doi_valid = False

    return CitationValidationEntry(
        uid=uid,
        doi_valid=doi_valid,
        year_valid=year_valid,
        author_valid=author_valid,
        venue_valid=venue_valid,
        url_reachable=url_valid,  # syntax check only; no HTTP request
        issues=all_issues,
    )


def _check_phantom_references(
    report: str,
    analyses: List[Dict[str, Any]],
) -> List[str]:
    """Find URLs in the report's References section that don't match any known source."""
    ref_urls = extract_reference_urls(report)
    known_urls: set[str] = set()
    for a in analyses:
        url = str(a.get("url") or "").strip()
        if url:
            known_urls.add(url.rstrip("/").lower())
        uid = str(a.get("uid") or "").strip()
        resolved = _uid_to_resolvable_url(uid)
        if resolved:
            known_urls.add(resolved.rstrip("/").lower())
        pdf_url = str(a.get("pdf_url") or "").strip()
        if pdf_url:
            known_urls.add(pdf_url.rstrip("/").lower())

    phantoms: List[str] = []
    for ref_url in ref_urls:
        normalized = ref_url.rstrip("/").lower()
        if normalized not in known_urls:
            phantoms.append(ref_url)
    return phantoms


def validate_citations(state: ResearchState) -> Dict[str, Any]:
    """Run citation metadata validation.

    Reads: analyses, report, claim_evidence_map
    Writes: review.citation_validation, review.reviewer_log (appends)
    """
    analyses: List[Dict[str, Any]] = list(sget(state, "analyses", []))
    report: str = str(sget(state, "report", "") or "")
    claim_map: List[Dict[str, Any]] = list(sget(state, "claim_evidence_map", []))

    # Validate each analysis entry
    entries: List[Dict[str, Any]] = []
    total_issues = 0
    for a in analyses:
        entry = _validate_single_analysis(a)
        entries.append(dict(entry))
        total_issues += len(entry.get("issues", []))

    # Check for phantom references (in report but not in analyses)
    phantom_refs = _check_phantom_references(report, analyses) if report else []

    # Check for orphaned claims (claims with evidence that has no valid URL)
    orphaned_claims = 0
    for c in claim_map:
        for e in c.get("evidence", []):
            url = str(e.get("url") or "").strip()
            uid = str(e.get("uid") or "").strip()
            if not url and not uid:
                orphaned_claims += 1

    # Build issues list
    issues: List[str] = []
    suggested_fixes: List[str] = []

    # Count sources with critical metadata failures
    sources_missing_url = sum(1 for e in entries if not e.get("url_reachable", True))
    sources_missing_year = sum(1 for e in entries if not e.get("year_valid", True))
    sources_missing_authors = sum(1 for e in entries if not e.get("author_valid", True))

    if sources_missing_url > 0:
        issues.append(f"{sources_missing_url}/{len(entries)} sources have invalid/missing URLs")
        suggested_fixes.append("Ensure all sources have resolvable URLs or DOI/arXiv identifiers")

    if sources_missing_year > len(entries) // 2:
        issues.append(f"{sources_missing_year}/{len(entries)} sources missing year metadata")

    if sources_missing_authors > len(entries) // 2:
        issues.append(f"{sources_missing_authors}/{len(entries)} sources missing author metadata")

    if phantom_refs:
        issues.append(f"{len(phantom_refs)} phantom reference(s) in report not matching any source")
        suggested_fixes.append("Remove fabricated references from the report")

    if orphaned_claims > 0:
        issues.append(f"{orphaned_claims} evidence item(s) in claim map have no URL or UID")

    # Determine verdict
    critical = len(phantom_refs) + sources_missing_url
    if critical == 0 and not issues:
        status = "pass"
        action = "continue"
        confidence = 0.9
    elif phantom_refs or critical > len(entries) // 3:
        status = "fail"
        action = "degrade"
        confidence = 0.7
    else:
        status = "warn"
        action = "continue"
        confidence = 0.8

    verdict = ReviewerVerdict(
        reviewer="citation_validator",
        status=status,
        action=action,
        issues=issues,
        suggested_fix=suggested_fixes,
        confidence=confidence,
    )

    citation_report = CitationValidationReport(
        entries=entries,
        verdict=verdict,
    )

    logger.info(
        "[CitationValidator] %d entries, %d issues, %d phantom refs → %s",
        len(entries), len(issues), len(phantom_refs), status,
    )

    existing_log = list(sget(state, "reviewer_log", []))
    existing_log.append(dict(verdict))

    return to_namespaced_update({
        "review": {
            "citation_validation": dict(citation_report),
            "reviewer_log": existing_log,
        },
        "status": f"Citation validation: {status} ({len(issues)} issues, {len(phantom_refs)} phantom refs)",
    })
