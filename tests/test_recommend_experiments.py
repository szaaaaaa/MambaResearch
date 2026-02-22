from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src.agent import nodes


class DomainDetectionTest(unittest.TestCase):
    def test_detect_domain_by_rules_ml_topic(self) -> None:
        ok = nodes._detect_domain_by_rules(
            "Fine-tuning transformer models for text classification",
            ["How does learning rate affect BERT fine-tuning?"],
        )
        self.assertTrue(ok)

    def test_detect_domain_by_rules_non_ml_topic(self) -> None:
        ok = nodes._detect_domain_by_rules(
            "History of the Roman Empire",
            ["What caused the fall of Rome?"],
        )
        self.assertFalse(ok)


class ExperimentPlanValidationTest(unittest.TestCase):
    def test_validate_experiment_plan_empty(self) -> None:
        issues = nodes._validate_experiment_plan({})
        self.assertIn("no_rq_experiments", issues)

    def test_validate_experiment_plan_valid(self) -> None:
        plan = {
            "rq_experiments": [
                {
                    "datasets": [{"name": "X", "url": "https://x.example"}],
                    "environment": {"python": "3.10", "cuda": "12.1", "pytorch": "2.3"},
                    "hyperparameters": {
                        "baseline": {"lr": 2e-5},
                        "search_space": {"lr": [1e-5, 5e-5]},
                    },
                    "run_commands": {"train": "python train.py", "eval": "python eval.py"},
                    "evidence_refs": [{"uid": "arxiv:1234"}],
                }
            ]
        }
        issues = nodes._validate_experiment_plan(plan)
        self.assertEqual(issues, [])


class RecommendExperimentsNodeTest(unittest.TestCase):
    @patch("src.agent.nodes._llm_call")
    def test_disabled_by_config_skips(self, mock_llm) -> None:
        state = {
            "topic": "Fine-tuning BERT for text classification",
            "research_questions": ["How does learning rate affect BERT fine-tuning?"],
            "_cfg": {
                "llm": {"model": "gpt-4.1-mini"},
                "agent": {"experiment_plan": {"enabled": False}},
            },
        }
        result = nodes.recommend_experiments(state)
        mock_llm.assert_not_called()
        self.assertEqual(result.get("experiment_plan", {}), {})
        self.assertFalse(bool(result.get("await_experiment_results", False)))

    @patch("src.agent.nodes._llm_call")
    def test_non_ml_topic_skips(self, mock_llm) -> None:
        state = {
            "topic": "History of medieval architecture",
            "research_questions": ["What styles emerged in 12th century?"],
            "_cfg": {"llm": {"model": "gpt-4.1-mini"}},
        }
        result = nodes.recommend_experiments(state)
        mock_llm.assert_not_called()
        self.assertEqual(result.get("experiment_plan", {}), {})
        self.assertFalse(bool(result.get("await_experiment_results", False)))

    @patch("src.agent.nodes._llm_call")
    def test_ml_topic_generates_plan(self, mock_llm) -> None:
        mock_plan = {
            "domain": "deep_learning",
            "subfield": "NLP",
            "task_type": "text classification",
            "rq_experiments": [
                {
                    "research_question": "test",
                    "task": "classification",
                    "datasets": [
                        {
                            "name": "SST-2",
                            "url": "https://example.com",
                            "license": "MIT",
                            "reason": "standard benchmark",
                        }
                    ],
                    "code_framework": {
                        "stack": "PyTorch",
                        "starter_repo": "https://github.com/example/repo",
                        "notes": "",
                    },
                    "environment": {
                        "python": "3.10",
                        "cuda": "12.1",
                        "pytorch": "2.3",
                        "gpu": "A100",
                        "deps": [],
                    },
                    "hyperparameters": {
                        "baseline": {"lr": 2e-5},
                        "search_space": {"lr": [1e-5, 5e-5]},
                    },
                    "run_commands": {"train": "python train.py", "eval": "python eval.py"},
                    "evaluation": {"metrics": ["accuracy"], "protocol": "3 seeds"},
                    "evidence_refs": [{"uid": "arxiv:1234", "url": "https://arxiv.org/abs/1234"}],
                }
            ],
        }
        mock_llm.side_effect = [
            json.dumps(
                {
                    "domain": "deep_learning",
                    "subfield": "NLP",
                    "task_type": "text classification",
                }
            ),
            json.dumps(mock_plan),
        ]
        state = {
            "topic": "Fine-tuning BERT for text classification using transformer models",
            "research_questions": ["How does learning rate affect BERT fine-tuning?"],
            "_cfg": {"llm": {"model": "gpt-4.1-mini", "temperature": 0.3}},
        }
        result = nodes.recommend_experiments(state)
        plan = result.get("experiment_plan", {})
        self.assertEqual(plan.get("domain"), "deep_learning")
        self.assertTrue(bool(result.get("await_experiment_results", False)))
        exp_results = result.get("experiment_results", {})
        self.assertEqual(exp_results.get("status"), "pending")
        self.assertEqual(mock_llm.call_count, 2)

    @patch("src.agent.nodes._llm_call")
    def test_require_human_results_false_does_not_wait(self, mock_llm) -> None:
        mock_plan = {
            "domain": "deep_learning",
            "subfield": "NLP",
            "task_type": "text classification",
            "rq_experiments": [
                {
                    "research_question": "test",
                    "task": "classification",
                    "datasets": [{"name": "SST-2", "url": "https://example.com"}],
                    "environment": {"python": "3.10", "cuda": "12.1", "pytorch": "2.3"},
                    "hyperparameters": {"baseline": {"lr": 2e-5}, "search_space": {"lr": [1e-5, 5e-5]}},
                    "run_commands": {"train": "python train.py", "eval": "python eval.py"},
                    "evidence_refs": [{"uid": "arxiv:1234"}],
                }
            ],
        }
        mock_llm.side_effect = [
            json.dumps(
                {
                    "domain": "deep_learning",
                    "subfield": "NLP",
                    "task_type": "text classification",
                }
            ),
            json.dumps(mock_plan),
        ]
        state = {
            "topic": "Fine-tuning BERT for text classification using transformer models",
            "research_questions": ["How does learning rate affect BERT fine-tuning?"],
            "_cfg": {
                "llm": {"model": "gpt-4.1-mini", "temperature": 0.3},
                "agent": {"experiment_plan": {"require_human_results": False}},
            },
        }
        result = nodes.recommend_experiments(state)
        self.assertFalse(bool(result.get("await_experiment_results", True)))

    @patch("src.agent.nodes._llm_call")
    def test_max_per_rq_caps_generated_groups(self, mock_llm) -> None:
        mock_plan = {
            "domain": "deep_learning",
            "subfield": "NLP",
            "task_type": "text classification",
            "rq_experiments": [
                {
                    "research_question": "RQ1",
                    "task": "classification",
                    "datasets": [{"name": "SST-2", "url": "https://example.com"}],
                    "environment": {"python": "3.10", "cuda": "12.1", "pytorch": "2.3"},
                    "hyperparameters": {"baseline": {"lr": 2e-5}, "search_space": {"lr": [1e-5]}},
                    "run_commands": {"train": "python train.py", "eval": "python eval.py"},
                    "evidence_refs": [{"uid": "arxiv:1"}],
                },
                {
                    "research_question": "RQ1",
                    "task": "classification",
                    "datasets": [{"name": "SST-2", "url": "https://example.com"}],
                    "environment": {"python": "3.10", "cuda": "12.1", "pytorch": "2.3"},
                    "hyperparameters": {"baseline": {"lr": 2e-5}, "search_space": {"lr": [1e-5]}},
                    "run_commands": {"train": "python train.py --x", "eval": "python eval.py --x"},
                    "evidence_refs": [{"uid": "arxiv:2"}],
                },
            ],
        }
        mock_llm.side_effect = [
            json.dumps({"domain": "deep_learning", "subfield": "NLP", "task_type": "text classification"}),
            json.dumps(mock_plan),
        ]
        state = {
            "topic": "Fine-tuning BERT for text classification using transformer models",
            "research_questions": ["How does learning rate affect BERT fine-tuning?"],
            "_cfg": {
                "llm": {"model": "gpt-4.1-mini", "temperature": 0.3},
                "agent": {"experiment_plan": {"max_per_rq": 1}},
            },
        }
        result = nodes.recommend_experiments(state)
        plan = result.get("experiment_plan", {})
        self.assertEqual(len(plan.get("rq_experiments", [])), 1)


class ExperimentResultsValidationTest(unittest.TestCase):
    def test_validate_experiment_results_invalid(self) -> None:
        issues = nodes._validate_experiment_results(
            {"status": "submitted", "runs": []},
            ["RQ1"],
        )
        self.assertIn("no_runs", issues)

    def test_validate_experiment_results_valid(self) -> None:
        results = {
            "status": "submitted",
            "runs": [
                {
                    "run_id": "rq1-expA",
                    "research_question": "RQ1",
                    "metrics": [{"name": "F1", "value": 80.0}],
                }
            ],
        }
        issues = nodes._validate_experiment_results(results, ["RQ1"])
        self.assertEqual(issues, [])

    def test_ingest_experiment_results_invalid_keeps_waiting(self) -> None:
        state = {
            "research_questions": ["RQ1"],
            "experiment_results": {"status": "submitted", "runs": []},
        }
        update = nodes.ingest_experiment_results(state)
        self.assertTrue(bool(update.get("await_experiment_results", False)))
        self.assertIn("validation_issues", update.get("experiment_results", {}))

    def test_ingest_experiment_results_pending_waits_without_validation_errors(self) -> None:
        state = {
            "research_questions": ["RQ1"],
            "experiment_results": {"status": "pending", "runs": []},
        }
        update = nodes.ingest_experiment_results(state)
        self.assertTrue(bool(update.get("await_experiment_results", False)))
        self.assertEqual(update.get("experiment_results", {}).get("status"), "pending")
        self.assertEqual(update.get("experiment_results", {}).get("validation_issues", []), [])

    def test_ingest_experiment_results_valid_unblocks(self) -> None:
        state = {
            "research_questions": ["RQ1"],
            "experiment_results": {
                "status": "submitted",
                "runs": [
                    {
                        "run_id": "rq1-expA",
                        "research_question": "RQ1",
                        "metrics": [{"name": "F1", "value": 80.0}],
                    }
                ],
            },
        }
        update = nodes.ingest_experiment_results(state)
        self.assertFalse(bool(update.get("await_experiment_results", True)))
        self.assertEqual(update.get("experiment_results", {}).get("status"), "validated")

    @patch("src.agent.nodes._llm_call")
    def test_ingest_experiment_results_normalizes_raw_results(self, mock_llm) -> None:
        normalized = {
            "status": "submitted",
            "runs": [
                {
                    "run_id": "rq1-expA",
                    "research_question": "RQ1",
                    "metrics": [{"name": "F1", "value": 80.0}],
                }
            ],
            "summaries": [],
            "validation_issues": [],
        }
        mock_llm.return_value = json.dumps(normalized)
        state = {
            "research_questions": ["RQ1"],
            "experiment_plan": {"rq_experiments": [{"research_question": "RQ1"}]},
            "experiment_results": {"raw_results": "run_id=rq1-expA, F1=80.0"},
            "_cfg": {"llm": {"model": "gpt-4.1-mini"}},
        }
        update = nodes.ingest_experiment_results(state)
        self.assertFalse(bool(update.get("await_experiment_results", True)))
        self.assertEqual(update.get("experiment_results", {}).get("status"), "validated")


if __name__ == "__main__":
    unittest.main()
