"""Tests for experiment reviewer."""
from __future__ import annotations

import unittest

from src.agent.reviewers.experiment_reviewer import review_experiment


def _make_state(*, experiment_plan=None):
    return {
        "topic": "concept drift",
        "planning": {"research_questions": [], "search_queries": [], "scope": {},
                      "budget": {}, "query_routes": {}, "_academic_queries": [], "_web_queries": []},
        "research": {"papers": [], "web_sources": [], "analyses": [],
                      "findings": [], "synthesis": "", "indexed_paper_ids": [],
                      "indexed_web_ids": [], "memory_summary": "",
                      "experiment_plan": experiment_plan or {},
                      "experiment_results": {}},
        "evidence": {"gaps": [], "claim_evidence_map": [], "evidence_audit_log": []},
        "review": {"retrieval_review": {}, "citation_validation": {},
                    "experiment_review": {}, "claim_verdicts": [], "reviewer_log": []},
        "report": {"report": "", "report_critic": {}, "repair_attempted": False,
                    "acceptance_metrics": {}},
        "_cfg": {},
    }


class TestExperimentReviewer(unittest.TestCase):
    def test_no_plan_passes(self):
        state = _make_state()
        result = review_experiment(state)
        review = result.get("review", {}).get("experiment_review", {})
        self.assertEqual(review["verdict"]["status"], "pass")

    def test_complete_plan_passes(self):
        plan = {
            "domain": "NLP",
            "rq_experiments": [
                {
                    "research_question": "How does drift affect BERT?",
                    "task": "classification",
                    "datasets": [
                        {"name": "IMDB train/test split", "url": "...", "reason": "standard split"},
                        {"name": "SST-2 validation set", "url": "...", "reason": "test generalization"},
                    ],
                    "hyperparameters": {
                        "baseline": {"lr": 0.001, "batch_size": 32, "epochs": 10},
                        "search_space": {"lr": [0.001, 0.01]},
                    },
                    "evaluation": {
                        "metrics": ["accuracy", "f1"],
                        "protocol": "5-fold cross-validation",
                    },
                    "environment": {"gpu": "A100"},
                }
            ],
        }
        state = _make_state(experiment_plan=plan)
        result = review_experiment(state)
        review = result.get("review", {}).get("experiment_review", {})
        self.assertIn(review["verdict"]["status"], ("pass", "warn"))

    def test_missing_baseline_flagged(self):
        plan = {
            "rq_experiments": [
                {
                    "research_question": "RQ1",
                    "task": "classification",
                    "datasets": [{"name": "D1"}],
                    "hyperparameters": {},
                    "evaluation": {"metrics": ["accuracy"], "protocol": "holdout"},
                }
            ],
        }
        state = _make_state(experiment_plan=plan)
        result = review_experiment(state)
        review = result.get("review", {}).get("experiment_review", {})
        self.assertGreater(len(review["baseline_issues"]), 0)

    def test_missing_metrics_flagged(self):
        plan = {
            "rq_experiments": [
                {
                    "research_question": "RQ1",
                    "hyperparameters": {"baseline": {"lr": 0.01}},
                    "evaluation": {"metrics": [], "protocol": "holdout"},
                    "datasets": [{"name": "D1"}],
                }
            ],
        }
        state = _make_state(experiment_plan=plan)
        result = review_experiment(state)
        review = result.get("review", {}).get("experiment_review", {})
        self.assertGreater(len(review["metric_issues"]), 0)

    def test_placeholder_metric_flagged(self):
        plan = {
            "rq_experiments": [
                {
                    "research_question": "RQ1",
                    "hyperparameters": {"baseline": {"lr": 0.01}},
                    "evaluation": {"metrics": ["tbd"], "protocol": "holdout"},
                    "datasets": [{"name": "D1"}],
                }
            ],
        }
        state = _make_state(experiment_plan=plan)
        result = review_experiment(state)
        review = result.get("review", {}).get("experiment_review", {})
        self.assertGreater(len(review["metric_issues"]), 0)

    def test_single_dataset_leakage_warning(self):
        plan = {
            "rq_experiments": [
                {
                    "research_question": "RQ1",
                    "datasets": [{"name": "CIFAR-10"}],
                    "hyperparameters": {"baseline": {"lr": 0.01}},
                    "evaluation": {"metrics": ["accuracy"], "protocol": "holdout"},
                }
            ],
        }
        state = _make_state(experiment_plan=plan)
        result = review_experiment(state)
        review = result.get("review", {}).get("experiment_review", {})
        self.assertGreater(len(review["leakage_risks"]), 0)


if __name__ == "__main__":
    unittest.main()
