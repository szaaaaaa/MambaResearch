from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src.agent import nodes


class RecommendExperimentsNodeTest(unittest.TestCase):
    @patch("src.agent.stages.experiments._runtime_llm_call")
    def test_disabled_by_config_skips(self, mock_llm) -> None:
        state = {
            "topic": "Fine-tuning BERT for text classification",
            "research_questions": ["How does learning rate affect BERT fine-tuning?"],
            "_cfg": {"llm": {"model": "gpt-4.1-mini"}, "agent": {"experiment_plan": {"enabled": False}}},
        }
        result = nodes.recommend_experiments(state)
        mock_llm.assert_not_called()
        self.assertEqual(result.get("experiment_plan", {}), {})
        self.assertFalse(bool(result.get("await_experiment_results", False)))

    @patch("src.agent.stages.experiments._runtime_llm_call")
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

    @patch("src.agent.stages.experiments._runtime_llm_call")
    def test_reexport_generates_plan_using_stage_patch_surface(self, mock_llm) -> None:
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
            json.dumps({"domain": "deep_learning", "subfield": "NLP", "task_type": "text classification"}),
            json.dumps(mock_plan),
        ]
        state = {
            "topic": "Fine-tuning BERT for text classification using transformer models",
            "research_questions": ["How does learning rate affect BERT fine-tuning?"],
            "_cfg": {"llm": {"model": "gpt-4.1-mini", "temperature": 0.3}},
        }
        result = nodes.recommend_experiments(state)
        self.assertEqual(result.get("experiment_plan", {}).get("domain"), "deep_learning")
        self.assertTrue(bool(result.get("await_experiment_results", False)))
        self.assertEqual(result.get("experiment_results", {}).get("status"), "pending")
        self.assertEqual(mock_llm.call_count, 2)


class ExperimentResultsNodeTest(unittest.TestCase):
    def test_ingest_experiment_results_invalid_keeps_waiting(self) -> None:
        state = {
            "research_questions": ["RQ1"],
            "experiment_results": {"status": "submitted", "runs": [{"run_id": "", "research_question": "RQ1", "metrics": []}]},
        }
        update = nodes.ingest_experiment_results(state)
        self.assertTrue(update.get("await_experiment_results"))
        self.assertIn("Experiment results invalid", update.get("status", ""))

    def test_ingest_experiment_results_pending_waits_without_validation_errors(self) -> None:
        state = {"research_questions": ["RQ1"], "experiment_results": {"status": "pending", "runs": []}}
        update = nodes.ingest_experiment_results(state)
        self.assertTrue(update.get("await_experiment_results"))
        self.assertEqual(update.get("experiment_results", {}).get("status"), "pending")

    def test_ingest_experiment_results_valid_unblocks(self) -> None:
        state = {
            "research_questions": ["RQ1"],
            "experiment_results": {
                "status": "submitted",
                "runs": [{"run_id": "rq1-expA", "research_question": "RQ1", "metrics": [{"name": "F1", "value": 80.0}]}],
            },
        }
        update = nodes.ingest_experiment_results(state)
        self.assertFalse(update.get("await_experiment_results"))
        self.assertEqual(update.get("experiment_results", {}).get("status"), "validated")

    @patch("src.agent.stages.experiments._runtime_llm_call")
    def test_ingest_experiment_results_normalizes_raw_results(self, mock_llm) -> None:
        normalized = {
            "status": "submitted",
            "runs": [{"run_id": "rq1-expA", "research_question": "RQ1", "metrics": [{"name": "F1", "value": 80.0}]}],
            "summaries": [],
        }
        mock_llm.return_value = json.dumps(normalized)
        state = {
            "research_questions": ["RQ1"],
            "experiment_plan": {"rq_experiments": [{"research_question": "RQ1"}]},
            "experiment_results": {"raw_results": "raw log"},
            "_cfg": {"llm": {"model": "gpt-4.1-mini"}},
        }
        update = nodes.ingest_experiment_results(state)
        self.assertFalse(update.get("await_experiment_results"))
        self.assertEqual(update.get("experiment_results", {}).get("status"), "validated")


if __name__ == "__main__":
    unittest.main()
