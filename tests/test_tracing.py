"""Tests for trace logger, trace grader, and benchmark."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
import unittest

from src.agent.tracing.trace_logger import TraceLogger, _snapshot_state
from src.agent.tracing.trace_grader import grade_trace, FailureType
from src.agent.tracing.benchmark import (
    BenchmarkTask,
    BENCHMARK_TASKS,
    evaluate_against_benchmark,
)


def _make_state(
    *,
    papers_count=6,
    analyses_count=6,
    claim_verdicts=None,
    retrieval_status="pass",
    citation_status="pass",
    experiment_status="pass",
    report="# Test Report\n\nSome content.\n\n## References\n- [P1](https://arxiv.org/abs/2401.00001)\n",
):
    papers = [{"uid": f"arxiv:{i}", "title": f"P{i}", "year": 2020 + i} for i in range(papers_count)]
    analyses = [{"uid": f"arxiv:{i}", "title": f"A{i}", "relevance_score": 0.8} for i in range(analyses_count)]
    claim_map = [
        {"claim": f"Claim {i}", "evidence": [{"uid": f"arxiv:{i}"}], "strength": "A"}
        for i in range(3)
    ]
    if claim_verdicts is None:
        claim_verdicts = [
            {"claim_id": "C1", "status": "supported", "confidence": 0.9},
            {"claim_id": "C2", "status": "supported", "confidence": 0.8},
            {"claim_id": "C3", "status": "partial", "confidence": 0.6},
        ]

    return {
        "topic": "concept drift detection",
        "planning": {
            "research_questions": ["How to detect drift?", "What methods work best?"],
            "search_queries": ["concept drift detection"],
            "scope": {}, "budget": {}, "query_routes": {},
            "_academic_queries": [], "_web_queries": [],
        },
        "research": {
            "papers": papers, "web_sources": [], "analyses": analyses,
            "findings": [], "synthesis": "Test synthesis",
            "indexed_paper_ids": [], "indexed_web_ids": [],
            "memory_summary": "", "experiment_plan": {}, "experiment_results": {},
        },
        "evidence": {
            "gaps": [], "claim_evidence_map": claim_map, "evidence_audit_log": [],
        },
        "review": {
            "retrieval_review": {
                "verdict": {"reviewer": "retrieval_reviewer", "status": retrieval_status,
                            "action": "continue", "issues": [], "confidence": 0.9},
            },
            "citation_validation": {
                "verdict": {"reviewer": "citation_validator", "status": citation_status,
                            "action": "continue", "issues": [], "confidence": 0.9},
                "entries": [{"uid": f"arxiv:{i}", "issues": []} for i in range(analyses_count)],
            },
            "experiment_review": {
                "verdict": {"reviewer": "experiment_reviewer", "status": experiment_status,
                            "action": "continue", "issues": [], "confidence": 0.9},
            },
            "claim_verdicts": claim_verdicts,
            "reviewer_log": [],
        },
        "report": {
            "report": report, "report_critic": {}, "repair_attempted": False,
            "acceptance_metrics": {},
        },
        "iteration": 1,
        "_cfg": {},
    }


# ── TraceLogger Tests ────────────────────────────────────────────────


class TestTraceLogger(unittest.TestCase):
    def test_log_stage_appends_entry(self):
        tl = TraceLogger()
        state = _make_state()
        tl.log_stage("plan_research", state, duration_ms=100)
        self.assertEqual(len(tl.entries), 1)
        self.assertEqual(tl.entries[0]["stage"], "plan_research")
        self.assertEqual(tl.entries[0]["type"], "node")
        self.assertEqual(tl.entries[0]["duration_ms"], 100)

    def test_log_reviewer_appends_verdict(self):
        tl = TraceLogger()
        state = _make_state()
        verdict = {"reviewer": "retrieval_reviewer", "status": "pass", "action": "continue",
                    "issues": [], "confidence": 0.9}
        tl.log_reviewer("review_retrieval", state, verdict, duration_ms=50)
        self.assertEqual(len(tl.entries), 1)
        self.assertEqual(tl.entries[0]["type"], "reviewer")
        self.assertEqual(tl.entries[0]["verdict"]["status"], "pass")

    def test_writes_to_disk(self):
        tmpdir = Path("tests/.tmp_trace_logger/run_dir")
        shutil.rmtree(tmpdir, ignore_errors=True)
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            tl = TraceLogger(run_dir=tmpdir)
            state = _make_state()
            tl.log_stage("test_node", state, duration_ms=10)
            tl.log_stage("test_node2", state, duration_ms=20)

            trace_file = tmpdir / "trace.jsonl"
            self.assertTrue(trace_file.exists())
            lines = trace_file.read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), 2)

            summary_path = tl.flush()
            self.assertIsNotNone(summary_path)
            self.assertTrue(summary_path.exists())
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["total_stages"], 2)
            self.assertEqual(summary["total_duration_ms"], 30)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_run_dir_no_crash(self):
        tl = TraceLogger(run_dir=None)
        state = _make_state()
        tl.log_stage("test", state, duration_ms=5)
        self.assertIsNone(tl.flush())


class TestSnapshotState(unittest.TestCase):
    def test_captures_counts(self):
        state = _make_state(papers_count=10, analyses_count=8)
        snap = _snapshot_state(state)
        self.assertEqual(snap["papers_count"], 10)
        self.assertEqual(snap["analyses_count"], 8)
        self.assertEqual(snap["claim_count"], 3)

    def test_captures_report_length(self):
        state = _make_state(report="# Report\n\nContent here.\n")
        snap = _snapshot_state(state)
        self.assertGreater(snap["report_chars"], 0)
        self.assertGreater(snap["report_lines"], 0)


# ── TraceGrader Tests ────────────────────────────────────────────────


class TestTraceGrader(unittest.TestCase):
    def test_all_pass_scores_high(self):
        state = _make_state()
        grade = grade_trace(state)
        self.assertGreaterEqual(grade["overall_score"], 0.7)
        self.assertEqual(grade["primary_failure_type"], "none")
        self.assertEqual(len(grade["fix_recommendations"]), 0)

    def test_retrieval_failure_classified(self):
        state = _make_state(retrieval_status="fail")
        grade = grade_trace(state)
        self.assertLess(grade["stage_scores"]["retrieval"], 0.5)
        self.assertEqual(grade["primary_failure_type"], "retrieval")
        self.assertGreater(len(grade["fix_recommendations"]), 0)

    def test_reasoning_failure_classified(self):
        verdicts = [
            {"claim_id": "C1", "status": "unsupported", "confidence": 0.3},
            {"claim_id": "C2", "status": "unsupported", "confidence": 0.3},
            {"claim_id": "C3", "status": "unsupported", "confidence": 0.3},
        ]
        state = _make_state(claim_verdicts=verdicts)
        grade = grade_trace(state)
        self.assertLess(grade["stage_scores"]["reasoning"], 0.3)
        self.assertEqual(grade["primary_failure_type"], "reasoning")

    def test_citation_failure_classified(self):
        state = _make_state(citation_status="fail")
        # Also make entries have issues
        for entry in state["review"]["citation_validation"]["entries"]:
            entry["issues"] = ["missing_url"]
        grade = grade_trace(state)
        self.assertLess(grade["stage_scores"]["citation"], 0.7)
        self.assertEqual(grade["primary_failure_type"], "citation")

    def test_experiment_failure_classified(self):
        state = _make_state(experiment_status="fail")
        # Need experiment plan to trigger non-neutral score
        state["research"]["experiment_plan"] = {
            "rq_experiments": [{"research_question": "RQ1"}]
        }
        grade = grade_trace(state)
        self.assertLess(grade["stage_scores"]["experiment"], 0.5)

    def test_no_reviews_gives_neutral(self):
        state = _make_state()
        state["review"] = {
            "retrieval_review": {},
            "citation_validation": {},
            "experiment_review": {},
            "claim_verdicts": [],
            "reviewer_log": [],
        }
        grade = grade_trace(state)
        self.assertGreaterEqual(grade["overall_score"], 0.3)
        self.assertLessEqual(grade["overall_score"], 0.7)


# ── Benchmark Tests ──────────────────────────────────────────────────


class TestBenchmark(unittest.TestCase):
    def test_builtin_tasks_exist(self):
        self.assertGreaterEqual(len(BENCHMARK_TASKS), 3)
        for task in BENCHMARK_TASKS:
            self.assertTrue(task.task_id)
            self.assertTrue(task.topic)
            self.assertTrue(task.expected_rq_keywords)

    def test_task_to_dict(self):
        task = BENCHMARK_TASKS[0]
        d = task.to_dict()
        self.assertEqual(d["task_id"], task.task_id)
        self.assertEqual(d["topic"], task.topic)

    def test_evaluate_passing_run(self):
        task = BenchmarkTask(
            task_id="TEST001",
            topic="concept drift detection",
            expected_rq_keywords=["drift", "detection"],
            expected_source_types=["arxiv"],
            min_sources=3,
            expected_claim_support_ratio=0.5,
        )
        state = _make_state()
        grade = grade_trace(state)
        result = evaluate_against_benchmark(task, state, grade)
        self.assertTrue(result["pass"])
        self.assertTrue(result["checks"]["rq_keyword_coverage"]["pass"])
        self.assertTrue(result["checks"]["min_sources"]["pass"])

    def test_evaluate_failing_run(self):
        task = BenchmarkTask(
            task_id="TEST002",
            topic="quantum computing",
            expected_rq_keywords=["quantum", "qubit", "entanglement"],
            expected_source_types=["arxiv"],
            min_sources=10,
            expected_claim_support_ratio=0.9,
        )
        state = _make_state(papers_count=2)
        grade = grade_trace(state)
        result = evaluate_against_benchmark(task, state, grade)
        # Should fail on at least one criterion
        self.assertFalse(result["pass"])


if __name__ == "__main__":
    unittest.main()
