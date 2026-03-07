"""Experiment Reviewer – deterministic checks on experiment plans.

Checks per update.md §7.5:
1. Baseline completeness (each RQ experiment has baseline config)
2. Metric-task match (metrics are non-empty and reasonable)
3. Ablation completeness (multiple hyperparams suggest ablation needed)
4. Data leakage indicators (train/test split, data contamination hints)
5. Compute feasibility (basic sanity on GPU/epoch requirements)

This does NOT call an LLM.  All checks are rule-based.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from src.agent.core.schemas import (
    ExperimentReview,
    ResearchState,
    ReviewerVerdict,
)
from src.agent.core.state_access import sget, to_namespaced_update

logger = logging.getLogger(__name__)


def _check_baselines(rq_experiments: List[Dict[str, Any]]) -> List[str]:
    """Check each RQ experiment has baseline hyperparameters."""
    issues: List[str] = []
    for i, exp in enumerate(rq_experiments):
        rq = str(exp.get("research_question") or f"RQ{i + 1}")[:60]
        hyper = exp.get("hyperparameters", {})
        if not isinstance(hyper, dict):
            issues.append(f"[{rq}] Missing hyperparameters entirely")
            continue
        baseline = hyper.get("baseline", {})
        if not isinstance(baseline, dict) or not baseline:
            issues.append(f"[{rq}] No baseline hyperparameters defined")
    return issues


def _check_metrics(rq_experiments: List[Dict[str, Any]]) -> List[str]:
    """Check each RQ experiment has evaluation metrics."""
    issues: List[str] = []
    for i, exp in enumerate(rq_experiments):
        rq = str(exp.get("research_question") or f"RQ{i + 1}")[:60]
        eval_spec = exp.get("evaluation", {})
        if not isinstance(eval_spec, dict):
            issues.append(f"[{rq}] Missing evaluation specification")
            continue
        metrics = eval_spec.get("metrics", [])
        if not isinstance(metrics, list) or not metrics:
            issues.append(f"[{rq}] No evaluation metrics defined")
            continue
        # Check for generic/placeholder metrics
        placeholder_metrics = {"metric", "score", "result", "value", "tbd", "todo"}
        for m in metrics:
            if str(m).strip().lower() in placeholder_metrics:
                issues.append(f"[{rq}] Placeholder metric detected: '{m}'")
    return issues


def _check_ablation(rq_experiments: List[Dict[str, Any]]) -> List[str]:
    """Check if ablation is needed based on search space complexity."""
    issues: List[str] = []
    for i, exp in enumerate(rq_experiments):
        rq = str(exp.get("research_question") or f"RQ{i + 1}")[:60]
        hyper = exp.get("hyperparameters", {})
        if not isinstance(hyper, dict):
            continue
        search_space = hyper.get("search_space", {})
        if not isinstance(search_space, dict):
            continue
        # If search space has multiple dimensions, ablation is recommended
        dims = sum(1 for v in search_space.values() if isinstance(v, list) and len(v) > 1)
        if dims >= 3:
            protocol = str(exp.get("evaluation", {}).get("protocol") or "").lower()
            if "ablation" not in protocol:
                issues.append(
                    f"[{rq}] Search space has {dims} dimensions but no ablation study mentioned"
                )
    return issues


def _check_leakage(rq_experiments: List[Dict[str, Any]]) -> List[str]:
    """Check for data leakage indicators."""
    issues: List[str] = []
    for i, exp in enumerate(rq_experiments):
        rq = str(exp.get("research_question") or f"RQ{i + 1}")[:60]
        datasets = exp.get("datasets", [])
        if not isinstance(datasets, list):
            continue
        # Check if any dataset has explicit train/test split info
        has_split_info = False
        for ds in datasets:
            if not isinstance(ds, dict):
                continue
            name = str(ds.get("name") or "").lower()
            reason = str(ds.get("reason") or "").lower()
            if any(kw in name + reason for kw in ("split", "train", "test", "validation", "holdout")):
                has_split_info = True
                break
        if datasets and not has_split_info:
            issues.append(f"[{rq}] No train/test split mentioned in dataset descriptions")

        # Check for single-dataset experiments (risk of overfitting)
        if len(datasets) == 1:
            issues.append(f"[{rq}] Single dataset — consider cross-dataset validation")
    return issues


def _check_compute(rq_experiments: List[Dict[str, Any]]) -> List[str]:
    """Basic compute feasibility checks."""
    issues: List[str] = []
    for i, exp in enumerate(rq_experiments):
        rq = str(exp.get("research_question") or f"RQ{i + 1}")[:60]
        env = exp.get("environment", {})
        if not isinstance(env, dict):
            continue
        gpu = str(env.get("gpu") or "").lower()
        hyper = exp.get("hyperparameters", {}) or {}
        baseline = hyper.get("baseline", {}) or {}
        epochs = baseline.get("epochs", 0)

        # Flag very high epoch counts
        if isinstance(epochs, (int, float)) and epochs > 200:
            issues.append(f"[{rq}] Very high epoch count ({epochs}) — check convergence")

        # Flag missing GPU spec for deep learning tasks
        task = str(exp.get("task") or "").lower()
        if any(kw in task for kw in ("train", "fine-tune", "finetune", "deep")) and not gpu:
            issues.append(f"[{rq}] Deep learning task but no GPU specified")
    return issues


def review_experiment(state: ResearchState) -> Dict[str, Any]:
    """Run experiment plan review.

    Reads: experiment_plan
    Writes: review.experiment_review, review.reviewer_log (appends)
    """
    experiment_plan: Dict[str, Any] = dict(sget(state, "experiment_plan", {}) or {})
    rq_experiments = experiment_plan.get("rq_experiments", [])
    if not isinstance(rq_experiments, list):
        rq_experiments = []

    if not rq_experiments:
        verdict = ReviewerVerdict(
            reviewer="experiment_reviewer",
            status="pass",
            action="continue",
            issues=["No experiment plan to review"],
            suggested_fix=[],
            confidence=0.95,
        )
        existing_log = list(sget(state, "reviewer_log", []))
        existing_log.append(dict(verdict))
        return to_namespaced_update({
            "review": {
                "experiment_review": dict(ExperimentReview(
                    verdict=verdict,
                    baseline_issues=[],
                    metric_issues=[],
                    ablation_issues=[],
                    leakage_risks=[],
                    compute_risks=[],
                )),
                "reviewer_log": existing_log,
            },
            "status": "Experiment review: no plan to review",
        })

    baseline_issues = _check_baselines(rq_experiments)
    metric_issues = _check_metrics(rq_experiments)
    ablation_issues = _check_ablation(rq_experiments)
    leakage_risks = _check_leakage(rq_experiments)
    compute_risks = _check_compute(rq_experiments)

    all_issues = baseline_issues + metric_issues + ablation_issues + leakage_risks + compute_risks
    critical = len(baseline_issues) + len(metric_issues)

    if not all_issues:
        status = "pass"
        action = "continue"
        confidence = 0.9
    elif critical > len(rq_experiments):
        status = "fail"
        action = "retry_upstream"
        confidence = 0.65
    else:
        status = "warn"
        action = "continue"
        confidence = 0.75

    suggested_fixes: List[str] = []
    if baseline_issues:
        suggested_fixes.append("Add baseline hyperparameters for all RQ experiments")
    if metric_issues:
        suggested_fixes.append("Define concrete evaluation metrics (not placeholders)")
    if leakage_risks:
        suggested_fixes.append("Declare data split strategy to avoid leakage")

    verdict = ReviewerVerdict(
        reviewer="experiment_reviewer",
        status=status,
        action=action,
        issues=all_issues,
        suggested_fix=suggested_fixes,
        confidence=confidence,
    )

    review = ExperimentReview(
        verdict=verdict,
        baseline_issues=baseline_issues,
        metric_issues=metric_issues,
        ablation_issues=ablation_issues,
        leakage_risks=leakage_risks,
        compute_risks=compute_risks,
    )

    logger.info(
        "[ExperimentReviewer] %d RQ experiments, %d issues → %s",
        len(rq_experiments), len(all_issues), status,
    )

    existing_log = list(sget(state, "reviewer_log", []))
    existing_log.append(dict(verdict))

    return to_namespaced_update({
        "review": {
            "experiment_review": dict(review),
            "reviewer_log": existing_log,
        },
        "status": f"Experiment review: {status} ({len(all_issues)} issues)",
    })
