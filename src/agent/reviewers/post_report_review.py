"""Post-report composite reviewer – runs claim extraction + citation validation.

This is a single LangGraph node that sequences two reviewers that both
operate on the final report and claim_evidence_map.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from src.agent.core.schemas import ResearchState
from src.agent.core.state_access import sget, to_namespaced_update
from src.agent.reviewers.claim_extractor import extract_and_assess_claims
from src.agent.reviewers.citation_validator import validate_citations

logger = logging.getLogger(__name__)


def _deep_merge_review(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two review namespace updates, concatenating list fields."""
    merged = dict(base)
    for key, value in patch.items():
        if key == "reviewer_log" and isinstance(value, list) and isinstance(merged.get(key), list):
            merged[key] = merged[key] + value
        else:
            merged[key] = value
    return merged


def review_claims_and_citations(state: ResearchState) -> Dict[str, Any]:
    """Run claim extraction then citation validation in sequence.

    Both write to the review namespace with different fields, so we
    merge their outputs.
    """
    # Run claim extractor
    claim_result = extract_and_assess_claims(state)

    # Apply claim result to a view of the state for citation validator
    patched_state = dict(state)
    claim_review = claim_result.get("review", {})
    existing_review = dict(state.get("review", {}))
    existing_review.update(claim_review)
    patched_state["review"] = existing_review

    # Run citation validator on patched state
    citation_result = validate_citations(patched_state)

    # Merge both review outputs
    merged_review = _deep_merge_review(
        claim_result.get("review", {}),
        citation_result.get("review", {}),
    )

    # Summarize
    claim_verdicts = merged_review.get("claim_verdicts", [])
    citation_val = merged_review.get("citation_validation", {})
    cit_verdict = citation_val.get("verdict", {})

    supported = sum(1 for v in claim_verdicts if v.get("status") == "supported")
    unsupported = sum(1 for v in claim_verdicts if v.get("status") == "unsupported")
    cit_status = cit_verdict.get("status", "unknown")

    status_msg = (
        f"Post-report review: claims={supported} supported/{unsupported} unsupported, "
        f"citations={cit_status}"
    )

    logger.info("[PostReportReview] %s", status_msg)

    return to_namespaced_update({
        "review": merged_review,
        "status": status_msg,
    })
