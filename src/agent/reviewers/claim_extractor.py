"""Claim Extractor – extracts verifiable claims from the synthesis/report.

Operates deterministically: parses the claim_evidence_map and the report text
to produce a structured ClaimSet that downstream validators can verify.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from src.agent.core.schemas import (
    ClaimSupportVerdict,
    ResearchState,
    ReviewerVerdict,
)
from src.agent.core.source_ranking import _STOPWORDS, _tokenize
from src.agent.core.state_access import sget, to_namespaced_update

logger = logging.getLogger(__name__)


def _extract_claims_from_map(claim_map: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract structured claims from the existing claim_evidence_map."""
    claims: List[Dict[str, Any]] = []
    for i, entry in enumerate(claim_map):
        claim_text = str(entry.get("claim") or "").strip()
        if not claim_text:
            continue
        evidence_uids = []
        for e in entry.get("evidence", []):
            uid = str(e.get("uid") or "").strip()
            url = str(e.get("url") or "").strip()
            evidence_uids.append(uid or url or "unknown")
        claims.append({
            "claim_id": f"C{i + 1}",
            "claim_text": claim_text,
            "research_question": str(entry.get("research_question") or ""),
            "evidence_refs": evidence_uids,
            "strength": str(entry.get("strength") or "C"),
            "caveat": str(entry.get("caveat") or ""),
        })
    return claims


def _extract_inline_claims_from_report(report: str) -> List[str]:
    """Extract sentences from report that look like factual claims.

    Heuristic: sentences that contain citation-like patterns (e.g., [Author, Year],
    (Author et al., Year), or markdown links) are likely claims.
    """
    if not report:
        return []
    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', report)
    claim_sentences: List[str] = []
    citation_pattern = re.compile(
        r'\[.*?\]\(https?://|'  # markdown link
        r'\(.*?et al\.,?\s*\d{4}\)|'  # (Author et al., 2024)
        r'\[.*?\d{4}.*?\]|'  # [Author 2024]
        r'arXiv:\d{4}\.\d{4,5}',  # arXiv reference
        re.IGNORECASE,
    )
    for s in sentences:
        s = s.strip()
        if not s or len(s) < 20:
            continue
        # Skip headings and list markers
        if s.startswith('#') or s.startswith('---'):
            continue
        if citation_pattern.search(s):
            claim_sentences.append(s)
    return claim_sentences[:20]  # cap to avoid explosion


def _assess_claim_support(
    claim: Dict[str, Any],
    analyses: List[Dict[str, Any]],
) -> ClaimSupportVerdict:
    """Deterministic support assessment based on evidence overlap."""
    claim_text = str(claim.get("claim_text") or "")
    claim_tokens = {t for t in _tokenize(claim_text) if t not in _STOPWORDS}
    evidence_refs = claim.get("evidence_refs", [])
    strength = claim.get("strength", "C")

    supporting: List[str] = []
    for ref_id in evidence_refs:
        # Find matching analysis
        for a in analyses:
            uid = str(a.get("uid") or "").strip()
            url = str(a.get("url") or "").strip()
            if ref_id and (ref_id == uid or ref_id == url):
                # Check token overlap between claim and analysis content
                a_text = " ".join([
                    str(a.get("summary") or ""),
                    " ".join(a.get("key_findings", []) if isinstance(a.get("key_findings"), list) else []),
                ])
                a_tokens = set(_tokenize(a_text))
                overlap = len(claim_tokens & a_tokens)
                if overlap >= 2:
                    supporting.append(ref_id)
                break

    # Determine support status
    if not evidence_refs:
        status = "unsupported"
        confidence = 0.3
    elif len(supporting) >= 2:
        status = "supported"
        confidence = 0.85
    elif len(supporting) == 1:
        status = "partial"
        confidence = 0.6
    else:
        status = "unsupported"
        confidence = 0.4

    # Downgrade if claim strength is already marked weak
    if strength == "C" and status == "supported":
        status = "partial"
        confidence = min(confidence, 0.5)

    return ClaimSupportVerdict(
        claim_id=claim.get("claim_id", ""),
        claim_text=claim_text[:200],
        status=status,
        supporting_evidence=supporting,
        confidence=confidence,
    )


def extract_and_assess_claims(state: ResearchState) -> Dict[str, Any]:
    """Extract claims from claim_evidence_map and assess support status.

    Reads: claim_evidence_map, analyses, report
    Writes: review.claim_verdicts, review.reviewer_log (appends)
    """
    claim_map: List[Dict[str, Any]] = list(sget(state, "claim_evidence_map", []))
    analyses: List[Dict[str, Any]] = list(sget(state, "analyses", []))
    report: str = str(sget(state, "report", "") or "")

    # Extract structured claims
    claims = _extract_claims_from_map(claim_map)

    if not claims:
        logger.info("[ClaimExtractor] No claims found in claim_evidence_map")
        verdict = ReviewerVerdict(
            reviewer="claim_extractor",
            status="warn",
            action="continue",
            issues=["No claims found in claim_evidence_map"],
            suggested_fix=["Ensure synthesis step produces claim_evidence_map"],
            confidence=0.5,
        )
        existing_log = list(sget(state, "reviewer_log", []))
        existing_log.append(dict(verdict))
        return to_namespaced_update({
            "review": {
                "claim_verdicts": [],
                "reviewer_log": existing_log,
            },
            "status": "Claim extraction: no claims found",
        })

    # Assess each claim
    verdicts: List[Dict[str, Any]] = []
    for claim in claims:
        v = _assess_claim_support(claim, analyses)
        verdicts.append(dict(v))

    # Summary stats
    supported = sum(1 for v in verdicts if v.get("status") == "supported")
    partial = sum(1 for v in verdicts if v.get("status") == "partial")
    unsupported = sum(1 for v in verdicts if v.get("status") == "unsupported")

    issues: List[str] = []
    if unsupported > 0:
        issues.append(f"{unsupported} claim(s) unsupported by evidence")
    if partial > len(verdicts) // 2:
        issues.append(f"Majority of claims ({partial}/{len(verdicts)}) only partially supported")

    if unsupported > len(verdicts) // 2:
        status = "fail"
        action = "retry_upstream"
    elif unsupported > 0 or partial > len(verdicts) // 2:
        status = "warn"
        action = "continue"
    else:
        status = "pass"
        action = "continue"

    verdict = ReviewerVerdict(
        reviewer="claim_extractor",
        status=status,
        action=action,
        issues=issues,
        suggested_fix=["Improve evidence retrieval for unsupported claims"] if unsupported else [],
        confidence=0.75,
    )

    logger.info(
        "[ClaimExtractor] %d claims: %d supported, %d partial, %d unsupported → %s",
        len(verdicts), supported, partial, unsupported, status,
    )

    existing_log = list(sget(state, "reviewer_log", []))
    existing_log.append(dict(verdict))

    return to_namespaced_update({
        "review": {
            "claim_verdicts": verdicts,
            "reviewer_log": existing_log,
        },
        "status": f"Claim assessment: {supported} supported, {partial} partial, {unsupported} unsupported",
    })
