from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


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


class GraphRuntimeTest(unittest.TestCase):
    def test_route_after_evaluate(self) -> None:
        self.assertEqual(graph._route_after_evaluate({"should_continue": True}), "plan_research")
        self.assertEqual(graph._route_after_evaluate({"should_continue": False}), "generate_report")
        self.assertEqual(graph._route_after_evaluate({}), "generate_report")

    def test_route_after_recommend_experiments(self) -> None:
        self.assertEqual(
            graph._route_after_recommend_experiments({"await_experiment_results": True}),
            "ingest_experiment_results",
        )
        self.assertEqual(
            graph._route_after_recommend_experiments({"await_experiment_results": False}),
            "evaluate_progress",
        )
        self.assertEqual(
            graph._route_after_recommend_experiments({}),
            "evaluate_progress",
        )

    def test_route_after_ingest_experiment_results(self) -> None:
        self.assertEqual(
            graph._route_after_ingest_experiment_results({"await_experiment_results": True}),
            "pause_for_human",
        )
        self.assertEqual(
            graph._route_after_ingest_experiment_results({"await_experiment_results": False}),
            "evaluate_progress",
        )
        self.assertEqual(
            graph._route_after_ingest_experiment_results({}),
            "evaluate_progress",
        )

    def test_build_graph_wiring_for_experiment_nodes(self) -> None:
        calls = {"nodes": [], "edges": [], "conditional": [], "entry": None}

        class _RecordingGraph:
            def __init__(self, *args, **kwargs):
                return None

            def add_node(self, name, fn):
                calls["nodes"].append(name)
                return None

            def set_entry_point(self, name):
                calls["entry"] = name
                return None

            def add_edge(self, start, end):
                calls["edges"].append((start, end))
                return None

            def add_conditional_edges(self, node, route_fn, mapping):
                calls["conditional"].append((node, mapping))
                return None

            def compile(self):
                return self

        with patch("src.agent.graph.StateGraph", _RecordingGraph):
            with patch("src.agent.graph.instrument_node", side_effect=lambda name, fn: fn):
                built = graph.build_graph()

        self.assertIsInstance(built, _RecordingGraph)
        self.assertEqual(calls["entry"], "plan_research")
        self.assertIn("recommend_experiments", calls["nodes"])
        self.assertIn("ingest_experiment_results", calls["nodes"])
        self.assertIn(("synthesize", "recommend_experiments"), calls["edges"])

        cond_nodes = [x[0] for x in calls["conditional"]]
        self.assertIn("recommend_experiments", cond_nodes)
        self.assertIn("ingest_experiment_results", cond_nodes)
        self.assertIn("evaluate_progress", cond_nodes)

        cond_map = {node: mapping for node, mapping in calls["conditional"]}
        self.assertEqual(
            cond_map["recommend_experiments"],
            {
                "ingest_experiment_results": "ingest_experiment_results",
                "evaluate_progress": "evaluate_progress",
            },
        )
        self.assertEqual(
            cond_map["ingest_experiment_results"],
            {
                "pause_for_human": graph.END,
                "evaluate_progress": "evaluate_progress",
            },
        )

    def test_run_research_injects_state_and_calls_app(self) -> None:
        captured = {}

        class _DummyApp:
            def invoke(self, state):
                captured["state"] = state
                return {"final": True, "run_id": state["run_id"]}

        cfg = {"agent": {"max_iterations": 4}, "sources": {"arxiv": {"enabled": True}}}

        with patch("src.agent.graph.build_graph", return_value=_DummyApp()):
            with patch("src.agent.graph.normalize_and_validate_config", side_effect=lambda x: dict(x)):
                with patch("src.agent.graph.uuid.uuid4", return_value="fixed-run-id"):
                    out = graph.run_research(topic="test-topic", cfg=cfg, root=".")

        self.assertEqual(out, {"final": True, "run_id": "fixed-run-id"})
        state = captured["state"]
        self.assertEqual(state["topic"], "test-topic")
        self.assertEqual(state["max_iterations"], 4)
        self.assertEqual(state["run_id"], "fixed-run-id")
        self.assertIn("research", state)
        self.assertIn("planning", state)
        self.assertIn("evidence", state)
        self.assertIn("report", state)
        self.assertIn("experiment_plan", state["research"])
        self.assertIn("experiment_results", state["research"])
        self.assertIn("await_experiment_results", state)
        self.assertEqual(state["_cfg"]["_run_id"], "fixed-run-id")
        self.assertEqual(Path(state["_cfg"]["_root"]), Path(".").resolve())
        self.assertIn("_budget_guard", state["_cfg"])


if __name__ == "__main__":
    unittest.main()
