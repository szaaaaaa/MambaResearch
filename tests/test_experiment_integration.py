from __future__ import annotations

import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch

from src.agent import nodes


def _import_graph_module():
    try:
        return importlib.import_module("src.agent.graph")
    except ModuleNotFoundError as exc:
        if exc.name not in {"langgraph", "langgraph.graph"}:
            raise
        fake_langgraph = types.ModuleType("langgraph")
        fake_graph = types.ModuleType("langgraph.graph")

        class _DummyStateGraph:
            def __init__(self, *args, **kwargs):
                pass

            def add_node(self, *args, **kwargs):
                return None

            def set_entry_point(self, *args, **kwargs):
                return None

            def add_edge(self, *args, **kwargs):
                return None

            def add_conditional_edges(self, *args, **kwargs):
                return None

            def compile(self):
                return self

        fake_graph.END = "__end__"
        fake_graph.StateGraph = _DummyStateGraph
        fake_langgraph.graph = fake_graph
        sys.modules["langgraph"] = fake_langgraph
        sys.modules["langgraph.graph"] = fake_graph
        return importlib.import_module("src.agent.graph")


graph = _import_graph_module()


class ExperimentIntegrationTest(unittest.TestCase):
    @patch("src.agent.nodes._llm_call")
    def test_ml_topic_pause_then_resume(self, mock_llm) -> None:
        mock_plan = {
            "domain": "deep_learning",
            "subfield": "nlp",
            "task_type": "classification",
            "rq_experiments": [
                {
                    "research_question": "RQ1",
                    "task": "classification",
                    "datasets": [{"name": "SST-2", "url": "https://example.com"}],
                    "environment": {"python": "3.10", "cuda": "12.1", "pytorch": "2.3"},
                    "hyperparameters": {"baseline": {"lr": 2e-5}, "search_space": {"lr": [1e-5]}},
                    "run_commands": {"train": "python train.py", "eval": "python eval.py"},
                    "evidence_refs": [{"uid": "arxiv:1234"}],
                }
            ],
        }
        mock_llm.side_effect = [
            json.dumps({"domain": "deep_learning", "subfield": "nlp", "task_type": "classification"}),
            json.dumps(mock_plan),
        ]

        base_state = {
            "topic": "Fine-tuning transformer models for text classification",
            "research_questions": ["RQ1"],
            "_cfg": {"llm": {"model": "gpt-4.1-mini"}, "agent": {"experiment_plan": {"require_human_results": True}}},
        }
        recommend_update = nodes.recommend_experiments(base_state)
        self.assertTrue(bool(recommend_update.get("await_experiment_results", False)))
        self.assertEqual(
            graph._route_after_recommend_experiments(recommend_update),
            "ingest_experiment_results",
        )

        paused_state = dict(base_state)
        paused_state.update(recommend_update)
        ingest_wait = nodes.ingest_experiment_results(paused_state)
        self.assertTrue(bool(ingest_wait.get("await_experiment_results", False)))
        self.assertEqual(
            graph._route_after_ingest_experiment_results(ingest_wait),
            "pause_for_human",
        )

        resumed_state = dict(paused_state)
        resumed_state["experiment_results"] = {
            "status": "submitted",
            "runs": [
                {
                    "run_id": "rq1-expA",
                    "research_question": "RQ1",
                    "metrics": [{"name": "F1", "value": 80.0}],
                }
            ],
            "summaries": [],
        }
        ingest_ok = nodes.ingest_experiment_results(resumed_state)
        self.assertFalse(bool(ingest_ok.get("await_experiment_results", True)))
        self.assertEqual(
            graph._route_after_ingest_experiment_results(ingest_ok),
            "evaluate_progress",
        )

    @patch("src.agent.nodes._llm_call")
    def test_non_ml_topic_noop_continues_to_evaluate(self, mock_llm) -> None:
        state = {
            "topic": "History of medieval architecture",
            "research_questions": ["What styles emerged in 12th century?"],
            "_cfg": {"llm": {"model": "gpt-4.1-mini"}},
        }
        update = nodes.recommend_experiments(state)
        mock_llm.assert_not_called()
        self.assertEqual(update.get("experiment_plan", {}), {})
        self.assertEqual(
            graph._route_after_recommend_experiments(update),
            "evaluate_progress",
        )


if __name__ == "__main__":
    unittest.main()
