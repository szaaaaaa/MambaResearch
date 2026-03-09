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

            def compile(self, **kwargs):
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

    def test_route_after_review_experiment(self) -> None:
        self.assertEqual(
            graph._route_after_review_experiment(
                {"await_experiment_results": True, "review": {"experiment_review": {"verdict": {"action": "continue"}}}}
            ),
            "ingest_experiment_results",
        )
        self.assertEqual(
            graph._route_after_review_experiment(
                {"await_experiment_results": False, "review": {"experiment_review": {"verdict": {"action": "continue"}}}}
            ),
            "evaluate_progress",
        )
        self.assertEqual(
            graph._route_after_review_experiment({}),
            "evaluate_progress",
        )

    def test_route_after_review_experiment_retries_then_blocks(self) -> None:
        self.assertEqual(
            graph._route_after_review_experiment(
                {
                    "_experiment_review_retries": 1,
                    "_cfg": {"reviewer": {"experiment": {"max_retries": 1}}},
                    "review": {"experiment_review": {"verdict": {"action": "retry_upstream"}}},
                }
            ),
            "recommend_experiments",
        )
        self.assertEqual(
            graph._route_after_review_experiment(
                {
                    "_experiment_review_retries": 2,
                    "_cfg": {"reviewer": {"experiment": {"max_retries": 1}}},
                    "review": {"experiment_review": {"verdict": {"action": "retry_upstream"}}},
                }
            ),
            "block",
        )

    def test_route_after_retrieval_review_respects_retry_and_terminal_actions(self) -> None:
        self.assertEqual(
            graph._route_after_retrieval_review(
                {
                    "_retrieval_review_retries": 1,
                    "_cfg": {"reviewer": {"retrieval": {"max_retries": 1}}},
                    "review": {"retrieval_review": {"verdict": {"action": "retry_upstream"}}},
                }
            ),
            "fetch_sources",
        )
        self.assertEqual(
            graph._route_after_retrieval_review(
                {
                    "review": {"retrieval_review": {"verdict": {"action": "degrade"}}},
                }
            ),
            "synthesize",
        )
        self.assertEqual(
            graph._route_after_retrieval_review(
                {
                    "review": {"retrieval_review": {"verdict": {"action": "block"}}},
                }
            ),
            "block",
        )
        self.assertEqual(
            graph._route_after_retrieval_review(
                {
                    "_retrieval_review_retries": 2,
                    "_cfg": {"reviewer": {"retrieval": {"max_retries": 1}}},
                    "review": {"retrieval_review": {"verdict": {"action": "retry_upstream"}}},
                }
            ),
            "block",
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

            def compile(self, **kwargs):
                calls["compile_kwargs"] = kwargs
                return self

        with patch("src.agent.graph.StateGraph", _RecordingGraph):
            with patch("src.agent.graph.instrument_node", side_effect=lambda name, fn: fn):
                built = graph.build_graph(checkpointer="cp")

        self.assertIsInstance(built, _RecordingGraph)
        self.assertEqual(calls["compile_kwargs"], {"checkpointer": "cp"})
        self.assertEqual(calls["entry"], "plan_research")
        self.assertIn("recommend_experiments", calls["nodes"])
        self.assertIn("review_experiment", calls["nodes"])
        self.assertIn("review_retrieval", calls["nodes"])
        self.assertIn("review_claims_and_citations", calls["nodes"])
        self.assertIn("ingest_experiment_results", calls["nodes"])
        self.assertIn(("synthesize", "recommend_experiments"), calls["edges"])
        self.assertIn(("recommend_experiments", "review_experiment"), calls["edges"])

        cond_nodes = [x[0] for x in calls["conditional"]]
        self.assertIn("review_experiment", cond_nodes)
        self.assertIn("review_retrieval", cond_nodes)
        self.assertIn("ingest_experiment_results", cond_nodes)
        self.assertIn("evaluate_progress", cond_nodes)

        cond_map = {node: mapping for node, mapping in calls["conditional"]}
        self.assertEqual(
            cond_map["review_experiment"],
            {
                "recommend_experiments": "recommend_experiments",
                "ingest_experiment_results": "ingest_experiment_results",
                "evaluate_progress": "evaluate_progress",
                "block": graph.END,
            },
        )
        self.assertEqual(
            cond_map["review_retrieval"],
            {
                "fetch_sources": "fetch_sources",
                "synthesize": "synthesize",
                "block": graph.END,
            },
        )
        self.assertEqual(
            cond_map["ingest_experiment_results"],
            {
                "pause_for_human": graph.END,
                "evaluate_progress": "evaluate_progress",
            },
        )

    def test_build_graph_phase1_nodes_use_skill_wrappers(self) -> None:
        recorded_nodes = {}

        class _RecordingGraph:
            def __init__(self, *args, **kwargs):
                return None

            def add_node(self, name, fn):
                recorded_nodes[name] = fn
                return None

            def set_entry_point(self, name):
                return None

            def add_edge(self, start, end):
                return None

            def add_conditional_edges(self, node, route_fn, mapping):
                return None

            def compile(self, **kwargs):
                return self

        with patch("src.agent.graph.StateGraph", _RecordingGraph):
            with patch("src.agent.graph.instrument_node", side_effect=lambda name, fn: fn):
                with patch("src.agent.graph._with_artifact_persistence", side_effect=lambda fn: fn):
                    graph.build_graph()

        self.assertEqual(recorded_nodes["plan_research"].__name__, "_skill_plan_research")
        self.assertEqual(recorded_nodes["fetch_sources"].__name__, "_skill_fetch_sources")
        self.assertEqual(recorded_nodes["index_sources"].__name__, "_skill_index_sources")
        self.assertEqual(recorded_nodes["analyze_sources"].__name__, "_skill_analyze_sources")
        self.assertEqual(recorded_nodes["review_retrieval"].__name__, "_skill_review_retrieval")
        self.assertEqual(recorded_nodes["synthesize"].__name__, "_skill_synthesize")
        self.assertEqual(recorded_nodes["recommend_experiments"].__name__, "recommend_experiments")
        self.assertEqual(recorded_nodes["ingest_experiment_results"].__name__, "ingest_experiment_results")
        self.assertEqual(recorded_nodes["review_experiment"].__name__, "review_experiment")
        self.assertEqual(recorded_nodes["evaluate_progress"].__name__, "evaluate_progress")
        self.assertEqual(recorded_nodes["generate_report"].__name__, "generate_report")
        self.assertEqual(recorded_nodes["review_claims_and_citations"].__name__, "review_claims_and_citations")

    def test_run_research_injects_state_and_calls_app(self) -> None:
        captured = {}

        class _DummyApp:
            def invoke(self, state, config=None):
                captured["state"] = state
                captured["config"] = config
                return {"final": True, "run_id": state["run_id"]}

        cfg = {"agent": {"max_iterations": 4}, "sources": {"arxiv": {"enabled": True}}}

        with patch("src.agent.graph.build_graph", return_value=_DummyApp()):
            with patch("src.agent.graph.build_checkpointer", return_value=None):
                with patch("src.agent.graph.normalize_and_validate_config", side_effect=lambda x: dict(x)):
                    with patch("src.agent.graph.uuid.uuid4", return_value="fixed-run-id"):
                        out = graph.run_research(topic="test-topic", cfg=cfg, root=".")

        self.assertTrue(out.get("final"))
        self.assertEqual(out["run_id"], "fixed-run-id")
        self.assertIn("_trace_grade", out)
        state = captured["state"]
        self.assertEqual(captured["config"], {"configurable": {"thread_id": "fixed-run-id"}})
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

    def test_run_research_resume_uses_checkpoint_thread_id(self) -> None:
        captured = {}

        class _DummyApp:
            def invoke(self, state, config=None):
                captured["state"] = state
                captured["config"] = config
                return {"final": True, "run_id": config["configurable"]["thread_id"]}

        cfg = {"agent": {"max_iterations": 2, "checkpointing": {"enabled": True}}}

        with patch("src.agent.graph.build_graph", return_value=_DummyApp()):
            with patch("src.agent.graph.build_checkpointer", return_value="cp"):
                with patch("src.agent.graph.normalize_and_validate_config", side_effect=lambda x: dict(x)):
                    out = graph.run_research(
                        topic="test-topic",
                        cfg=cfg,
                        root=".",
                        resume_run_id="resume-run-id",
                    )

        self.assertTrue(out.get("final"))
        self.assertEqual(out["run_id"], "resume-run-id")
        self.assertIn("_trace_grade", out)
        self.assertIsNone(captured["state"])
        self.assertEqual(captured["config"], {"configurable": {"thread_id": "resume-run-id"}})


if __name__ == "__main__":
    unittest.main()
