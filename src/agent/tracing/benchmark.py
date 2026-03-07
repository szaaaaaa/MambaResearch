"""Benchmark task set for evaluating pipeline quality.

Provides a minimal set of benchmark tasks with expected properties
that can be used to regression-test the pipeline.

Each benchmark task defines:
- topic: research topic string
- expected_rq_keywords: keywords that should appear in research questions
- expected_source_types: which source backends should find results
- min_sources: minimum number of sources expected
- expected_claim_support_ratio: minimum fraction of claims that should be supported
- notes: human-readable description
"""
from __future__ import annotations

from typing import Any, Dict, List


class BenchmarkTask:
    """A single benchmark evaluation task."""

    def __init__(
        self,
        *,
        task_id: str,
        topic: str,
        expected_rq_keywords: List[str],
        expected_source_types: List[str],
        min_sources: int = 5,
        expected_claim_support_ratio: float = 0.5,
        notes: str = "",
    ):
        self.task_id = task_id
        self.topic = topic
        self.expected_rq_keywords = expected_rq_keywords
        self.expected_source_types = expected_source_types
        self.min_sources = min_sources
        self.expected_claim_support_ratio = expected_claim_support_ratio
        self.notes = notes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "topic": self.topic,
            "expected_rq_keywords": self.expected_rq_keywords,
            "expected_source_types": self.expected_source_types,
            "min_sources": self.min_sources,
            "expected_claim_support_ratio": self.expected_claim_support_ratio,
            "notes": self.notes,
        }


def evaluate_against_benchmark(
    task: BenchmarkTask,
    final_state: Dict[str, Any],
    trace_grade: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate a pipeline run against a benchmark task's expectations.

    Returns a dict with pass/fail for each criterion.
    """
    from src.agent.core.state_access import sget

    results: Dict[str, Any] = {"task_id": task.task_id, "checks": {}}

    # 1. RQ keyword coverage
    rqs = sget(final_state, "research_questions", [])
    rq_text = " ".join(str(q).lower() for q in rqs) if isinstance(rqs, list) else ""
    kw_hits = sum(1 for kw in task.expected_rq_keywords if kw.lower() in rq_text)
    kw_ratio = kw_hits / max(1, len(task.expected_rq_keywords))
    results["checks"]["rq_keyword_coverage"] = {
        "pass": kw_ratio >= 0.5,
        "ratio": round(kw_ratio, 3),
        "hits": kw_hits,
        "expected": len(task.expected_rq_keywords),
    }

    # 2. Source count
    papers = sget(final_state, "papers", [])
    web = sget(final_state, "web_sources", [])
    total_sources = (len(papers) if isinstance(papers, list) else 0) + (len(web) if isinstance(web, list) else 0)
    results["checks"]["min_sources"] = {
        "pass": total_sources >= task.min_sources,
        "actual": total_sources,
        "expected": task.min_sources,
    }

    # 3. Claim support ratio
    review = final_state.get("review", {})
    claim_verdicts = review.get("claim_verdicts", []) if isinstance(review, dict) else []
    if claim_verdicts:
        supported = sum(1 for v in claim_verdicts if v.get("status") in ("supported", "partial"))
        ratio = supported / max(1, len(claim_verdicts))
    else:
        ratio = 0.0
    results["checks"]["claim_support_ratio"] = {
        "pass": ratio >= task.expected_claim_support_ratio,
        "actual": round(ratio, 3),
        "expected": task.expected_claim_support_ratio,
    }

    # 4. Overall trace grade
    overall = trace_grade.get("overall_score", 0.0)
    results["checks"]["overall_grade"] = {
        "pass": overall >= 0.6,
        "score": overall,
        "primary_failure": trace_grade.get("primary_failure_type", "unknown"),
    }

    # Summary
    all_pass = all(c.get("pass", False) for c in results["checks"].values())
    results["pass"] = all_pass

    return results


# ── Built-in benchmark tasks ─────────────────────────────────────────

BENCHMARK_TASKS: List[BenchmarkTask] = [
    BenchmarkTask(
        task_id="BM001",
        topic="Concept drift detection in online machine learning systems",
        expected_rq_keywords=["concept", "drift", "detection", "online"],
        expected_source_types=["arxiv"],
        min_sources=5,
        expected_claim_support_ratio=0.5,
        notes="Core ML topic with rich arxiv coverage",
    ),
    BenchmarkTask(
        task_id="BM002",
        topic="Retrieval-augmented generation for knowledge-intensive NLP tasks",
        expected_rq_keywords=["retrieval", "augmented", "generation", "knowledge"],
        expected_source_types=["arxiv", "web"],
        min_sources=5,
        expected_claim_support_ratio=0.5,
        notes="RAG topic — should trigger good academic + web coverage",
    ),
    BenchmarkTask(
        task_id="BM003",
        topic="Impact of transformer architecture on protein structure prediction",
        expected_rq_keywords=["transformer", "protein", "structure", "prediction"],
        expected_source_types=["arxiv"],
        min_sources=3,
        expected_claim_support_ratio=0.4,
        notes="Cross-domain topic — bioinformatics + ML",
    ),
]
