"""Trace Grader – classifies failure types and scores pipeline runs.

Failure taxonomy (per update.md §10):
- RETRIEVAL:  insufficient/low-quality sources, missing RQ coverage
- REASONING:  synthesis weak, claims unsupported despite available evidence
- CITATION:   phantom references, metadata errors, missing URLs
- EXPERIMENT: incomplete plans, missing baselines/metrics, leakage risks
- NONE:       no significant failures detected

The grader operates on the final state (or trace entries) and produces
a TraceGrade with per-stage scores and a primary failure classification.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List

from src.agent.core.state_access import sget

logger = logging.getLogger(__name__)


class FailureType(str, Enum):
    NONE = "none"
    RETRIEVAL = "retrieval"
    REASONING = "reasoning"
    CITATION = "citation"
    EXPERIMENT = "experiment"


def _score_retrieval(state: Dict[str, Any]) -> tuple[float, List[str]]:
    """Score retrieval quality from review namespace (0-1, higher = better)."""
    review = state.get("review", {})
    ret_review = review.get("retrieval_review", {})
    verdict = ret_review.get("verdict", {})
    issues = verdict.get("issues", [])

    if not ret_review:
        # No review ran — neutral score
        return 0.5, ["retrieval_review_not_run"]

    status = verdict.get("status", "unknown")
    if status == "pass":
        return 1.0, []
    elif status == "warn":
        return 0.7, [f"retrieval_warn: {len(issues)} issues"]
    else:
        return 0.3, [f"retrieval_fail: {len(issues)} issues"] + issues[:3]


def _score_reasoning(state: Dict[str, Any]) -> tuple[float, List[str]]:
    """Score reasoning/claim support quality (0-1)."""
    review = state.get("review", {})
    claim_verdicts = review.get("claim_verdicts", [])
    recommendations: List[str] = []

    if not claim_verdicts:
        return 0.5, ["no_claim_verdicts_available"]

    total = len(claim_verdicts)
    supported = sum(1 for v in claim_verdicts if v.get("status") == "supported")
    partial = sum(1 for v in claim_verdicts if v.get("status") == "partial")
    unsupported = sum(1 for v in claim_verdicts if v.get("status") == "unsupported")

    score = (supported + 0.5 * partial) / max(1, total)

    if unsupported > 0:
        recommendations.append(f"{unsupported}/{total} claims unsupported")
    if partial > total // 2:
        recommendations.append(f"majority of claims only partially supported")

    return round(score, 3), recommendations


def _score_citation(state: Dict[str, Any]) -> tuple[float, List[str]]:
    """Score citation quality from validation report (0-1)."""
    review = state.get("review", {})
    cit_val = review.get("citation_validation", {})
    verdict = cit_val.get("verdict", {})
    entries = cit_val.get("entries", [])
    recommendations: List[str] = []

    if not cit_val:
        return 0.5, ["citation_validation_not_run"]

    status = verdict.get("status", "unknown")
    issues = verdict.get("issues", [])

    if not entries:
        return 0.5, ["no_citation_entries"]

    # Count clean entries
    clean = sum(1 for e in entries if not e.get("issues"))
    ratio = clean / max(1, len(entries))

    if status == "pass":
        score = max(0.9, ratio)
    elif status == "warn":
        score = max(0.5, ratio * 0.8)
    else:
        score = ratio * 0.6

    if ratio < 0.7:
        recommendations.append(f"only {clean}/{len(entries)} sources have clean metadata")
    for issue in issues[:3]:
        recommendations.append(issue)

    return round(score, 3), recommendations


def _score_experiment(state: Dict[str, Any]) -> tuple[float, List[str]]:
    """Score experiment plan quality (0-1)."""
    review = state.get("review", {})
    exp_review = review.get("experiment_review", {})
    verdict = exp_review.get("verdict", {})
    recommendations: List[str] = []

    if not exp_review:
        # No experiment plan → neutral (not all topics need experiments)
        exp_plan = sget(state, "experiment_plan", {})
        if isinstance(exp_plan, dict) and exp_plan.get("rq_experiments"):
            return 0.4, ["experiment_review_not_run_but_plan_exists"]
        return 1.0, []  # no plan needed

    status = verdict.get("status", "unknown")
    issues = verdict.get("issues", [])

    if status == "pass":
        return 1.0, []
    elif status == "warn":
        return 0.7, [f"experiment_warn: {len(issues)} issues"]
    else:
        return 0.3, [f"experiment_fail: {len(issues)} issues"] + issues[:3]


def _classify_primary_failure(scores: Dict[str, float]) -> FailureType:
    """Determine the primary failure type from dimension scores."""
    # If all scores are above threshold, no failure
    if all(s >= 0.7 for s in scores.values()):
        return FailureType.NONE

    # Find the weakest dimension
    worst = min(scores, key=scores.get)  # type: ignore[arg-type]
    return FailureType(worst)


def grade_trace(state: Dict[str, Any]) -> Dict[str, Any]:
    """Grade a completed pipeline run.

    Parameters
    ----------
    state : dict
        The final ResearchState after pipeline completion.

    Returns
    -------
    dict
        TraceGrade with:
        - stage_scores: {retrieval, reasoning, citation, experiment} → float
        - primary_failure_type: FailureType
        - fix_recommendations: list of actionable suggestions
        - overall_score: weighted average
    """
    ret_score, ret_recs = _score_retrieval(state)
    rea_score, rea_recs = _score_reasoning(state)
    cit_score, cit_recs = _score_citation(state)
    exp_score, exp_recs = _score_experiment(state)

    scores = {
        "retrieval": ret_score,
        "reasoning": rea_score,
        "citation": cit_score,
        "experiment": exp_score,
    }

    # Weighted average (retrieval and reasoning matter most)
    weights = {"retrieval": 0.3, "reasoning": 0.3, "citation": 0.25, "experiment": 0.15}
    overall = sum(scores[k] * weights[k] for k in scores)

    primary_failure = _classify_primary_failure(scores)

    # Build fix recommendations
    fix_recs: List[str] = []
    if primary_failure == FailureType.RETRIEVAL:
        fix_recs.append("Improve search queries or enable additional source backends")
        fix_recs.extend(ret_recs[:2])
    elif primary_failure == FailureType.REASONING:
        fix_recs.append("Strengthen evidence retrieval for unsupported claims")
        fix_recs.extend(rea_recs[:2])
    elif primary_failure == FailureType.CITATION:
        fix_recs.append("Fix citation metadata and remove phantom references")
        fix_recs.extend(cit_recs[:2])
    elif primary_failure == FailureType.EXPERIMENT:
        fix_recs.append("Complete experiment plan with baselines, metrics, and data splits")
        fix_recs.extend(exp_recs[:2])

    grade = {
        "stage_scores": scores,
        "overall_score": round(overall, 3),
        "primary_failure_type": primary_failure.value,
        "fix_recommendations": fix_recs,
        "details": {
            "retrieval": ret_recs,
            "reasoning": rea_recs,
            "citation": cit_recs,
            "experiment": exp_recs,
        },
    }

    logger.info(
        "[TraceGrader] overall=%.2f primary_failure=%s scores=%s",
        overall, primary_failure.value, scores,
    )

    return grade
