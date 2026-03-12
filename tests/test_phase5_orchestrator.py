from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.agent.core.artifact_utils import make_artifact, records_to_artifacts
from src.agent.runtime.orchestrator import ResearchOrchestrator


def _artifact(artifact_type: str, payload: dict) -> object:
    return records_to_artifacts(
        [make_artifact(artifact_type=artifact_type, producer="unit_test", payload=payload, source_inputs=["seed"])]
    )[0]


class Phase5OrchestratorTest(unittest.TestCase):
    def test_orchestrator_passes_conductor_artifacts_to_researcher(self) -> None:
        class _Conductor:
            def __init__(self, *, context, state):
                self.state = state
                self.policy = SimpleNamespace(max_retries=1)

            def plan(self, context):
                output = [
                    _artifact("SearchPlan", {"research_questions": ["rq"], "search_queries": ["q"], "query_routes": {}})
                ]
                self.state["_artifact_objects"] = output
                self.state["artifacts"] = [artifact.to_record() for artifact in output]
                return ["search_literature"]

        class _Researcher:
            def __init__(self, *, context, state):
                self.state = state

            def execute_plan(self, skill_ids, artifacts):
                artifact_types = [artifact.artifact_type for artifact in artifacts]
                if "SearchPlan" not in artifact_types:
                    raise AssertionError("Researcher did not receive conductor SearchPlan artifact")
                output = list(artifacts)
                self.state["_artifact_objects"] = output
                return output

        class _Experimenter:
            def __init__(self, *, context, state):
                self.state = state

            def design(self, artifacts):
                raise AssertionError("Experimenter should not run")

        class _Analyst:
            def __init__(self, *, context, state):
                self.state = state

            def analyze(self, artifacts):
                raise AssertionError("Analyst should not run")

        class _Writer:
            def __init__(self, *, context, state):
                self.state = state

            def write(self, artifacts):
                output = list(artifacts) + [_artifact("ResearchReport", {"report": "ok"})]
                self.state["_artifact_objects"] = output
                self.state["report"] = {"report": "ok"}
                return output

        class _Critic:
            def __init__(self, *, context, state):
                self.state = state

            def evaluate(self, artifacts):
                return "pass", _artifact("CritiqueReport", {"verdict": {"action": "continue"}, "details": {}})

        with patch("src.agent.runtime.orchestrator.ensure_plugins_registered"):
            with patch("src.agent.runtime.orchestrator.ConductorAgent", _Conductor):
                with patch("src.agent.runtime.orchestrator.ResearcherAgent", _Researcher):
                    with patch("src.agent.runtime.orchestrator.ExperimenterAgent", _Experimenter):
                        with patch("src.agent.runtime.orchestrator.AnalystAgent", _Analyst):
                            with patch("src.agent.runtime.orchestrator.WriterAgent", _Writer):
                                with patch("src.agent.runtime.orchestrator.CriticAgent", _Critic):
                                    orchestrator = ResearchOrchestrator(cfg={"llm": {"provider": "gemini"}}, root=".")
                                    state = orchestrator.run(
                                        topic="topic",
                                        route_roles=["conductor", "researcher", "critic", "writer"],
                                    )

        self.assertEqual(state["status"], "Research OS orchestration completed")
        self.assertEqual(state["report"]["report"], "ok")

    def test_orchestrator_pass_flow_with_all_six_roles(self) -> None:
        class _Conductor:
            def __init__(self, *, context, state):
                self.policy = SimpleNamespace(max_retries=1)

            def plan(self, context):
                return ["search_literature", "parse_paper_bundle", "extract_paper_notes", "build_related_work_matrix"]

        class _Researcher:
            def __init__(self, *, context, state):
                self.state = state

            def execute_plan(self, skill_ids, artifacts):
                output = list(artifacts) + [
                    _artifact("TopicBrief", {"topic": "t", "scope": {}}),
                    _artifact("SearchPlan", {"research_questions": ["rq"], "search_queries": ["q"], "query_routes": {}}),
                    _artifact("CorpusSnapshot", {"papers": [], "web_sources": [], "indexed_paper_ids": []}),
                    _artifact(
                        "PaperNote",
                        {
                            "uid": "p1",
                            "title": "Paper",
                            "source": "arxiv",
                            "source_type": "paper",
                            "summary": "This paper argues for modular agent evaluation pipelines.",
                            "key_findings": ["Explicit metrics improve comparability across runs."],
                            "methodology": "case study",
                            "credibility": "high",
                            "relevance_score": 0.91,
                        },
                    ),
                    _artifact("RelatedWorkMatrix", {"narrative": "narrative", "claims": []}),
                    _artifact("GapMap", {"gaps": ["g1"]}),
                ]
                self.state["_artifact_objects"] = output
                self.state["research_questions"] = ["rq"]
                self.state["analyses"] = [
                    {
                        "uid": "p1",
                        "title": "Paper",
                        "source": "arxiv",
                        "source_type": "paper",
                        "summary": "This paper argues for modular agent evaluation pipelines.",
                        "key_findings": ["Explicit metrics improve comparability across runs."],
                        "methodology": "case study",
                        "credibility": "high",
                        "relevance_score": 0.91,
                    }
                ]
                self.state["findings"] = ["Explicit metrics improve comparability across runs."]
                self.state["gaps"] = ["g1"]
                self.state["synthesis"] = "narrative"
                return output

        class _Experimenter:
            def __init__(self, *, context, state):
                self.state = state

            def design(self, artifacts):
                output = list(artifacts) + [
                    _artifact(
                        "ExperimentPlan",
                        {
                            "domain": "machine_learning",
                            "subfield": "nlp",
                            "task_type": "classification",
                            "rq_experiments": [{"research_question": "rq"}],
                        },
                    ),
                    _artifact(
                        "ExperimentResults",
                        {
                            "status": "validated",
                            "runs": [
                                {
                                    "run_id": "run-1",
                                    "research_question": "rq",
                                    "metrics": [{"name": "F1", "value": 0.84, "higher_is_better": True}],
                                }
                            ],
                            "summaries": [{"research_question": "rq", "best_run_id": "run-1", "conclusion": "good"}],
                            "validation_issues": [],
                        },
                    ),
                ]
                self.state["_artifact_objects"] = output
                self.state["experiment_plan"] = {
                    "domain": "machine_learning",
                    "subfield": "nlp",
                    "task_type": "classification",
                    "rq_experiments": [{"research_question": "rq"}],
                }
                self.state["experiment_results"] = {
                    "status": "validated",
                    "runs": [
                        {
                            "run_id": "run-1",
                            "research_question": "rq",
                            "metrics": [{"name": "F1", "value": 0.84, "higher_is_better": True}],
                        }
                    ],
                    "summaries": [{"research_question": "rq", "best_run_id": "run-1", "conclusion": "good"}],
                    "validation_issues": [],
                }
                self.state["await_experiment_results"] = False
                return output

        class _Analyst:
            def __init__(self, *, context, state):
                self.state = state

            def analyze(self, artifacts):
                output = list(artifacts) + [
                    _artifact(
                        "ExperimentAnalysis",
                        {
                            "summary": "Validated one experiment run.",
                            "key_findings": ["Best F1 = 0.84 from run-1."],
                            "performance_metrics": {"validated": True, "run_count": 1},
                        },
                    ),
                    _artifact("PerformanceMetrics", {"validated": True, "run_count": 1}),
                ]
                self.state["_artifact_objects"] = output
                self.state["result_analysis"] = {
                    "summary": "Validated one experiment run.",
                    "key_findings": ["Best F1 = 0.84 from run-1."],
                    "performance_metrics": {"validated": True, "run_count": 1},
                }
                self.state["performance_metrics"] = {"validated": True, "run_count": 1}
                return output

        class _Writer:
            def __init__(self, *, context, state):
                self.state = state

            def write(self, artifacts):
                output = list(artifacts) + [
                    _artifact(
                        "ResearchReport",
                        {
                            "report": "# Final Report\n\nValidated one run.",
                            "report_critic": {"pass": True},
                            "repair_attempted": False,
                            "acceptance_metrics": {"note": "ok"},
                        },
                    )
                ]
                self.state["_artifact_objects"] = output
                self.state["report"] = {"report": "# Final Report\n\nValidated one run."}
                self.state["report_critic"] = {"pass": True}
                self.state["acceptance_metrics"] = {"note": "ok"}
                return output

        class _Critic:
            def __init__(self, *, context, state):
                self.state = state

            def evaluate(self, artifacts):
                return "pass", _artifact("CritiqueReport", {"verdict": {"action": "continue"}, "details": {}})

        with patch("src.agent.runtime.orchestrator.ensure_plugins_registered"):
            with patch("src.agent.runtime.orchestrator.ConductorAgent", _Conductor):
                with patch("src.agent.runtime.orchestrator.ResearcherAgent", _Researcher):
                    with patch("src.agent.runtime.orchestrator.ExperimenterAgent", _Experimenter):
                        with patch("src.agent.runtime.orchestrator.AnalystAgent", _Analyst):
                            with patch("src.agent.runtime.orchestrator.WriterAgent", _Writer):
                                with patch("src.agent.runtime.orchestrator.CriticAgent", _Critic):
                                    orchestrator = ResearchOrchestrator(cfg={"llm": {"provider": "gemini"}}, root=".")
                                    state = orchestrator.run(
                                        topic="topic",
                                        route_roles=["conductor", "researcher", "experimenter", "analyst", "writer", "critic"],
                                    )

        self.assertEqual(state["status"], "Research OS orchestration completed")
        self.assertEqual(state["role_status"]["experimenter"], "completed")
        self.assertEqual(state["role_status"]["analyst"], "completed")
        self.assertEqual(state["role_status"]["writer"], "completed")
        self.assertIn("# Final Report", state["report"]["report"])
        self.assertEqual(state["result_analysis"]["summary"], "Validated one experiment run.")
        self.assertTrue(state["performance_metrics"]["validated"])
        artifact_types = [artifact["artifact_type"] for artifact in state["artifacts"]]
        self.assertIn("ExperimentPlan", artifact_types)
        self.assertIn("ExperimentResults", artifact_types)
        self.assertIn("ExperimentAnalysis", artifact_types)
        self.assertIn("PerformanceMetrics", artifact_types)
        self.assertIn("ResearchReport", artifact_types)

    def test_orchestrator_revise_then_pass_runs_downstream_roles_once(self) -> None:
        class _Conductor:
            calls = 0

            def __init__(self, *, context, state):
                self.policy = SimpleNamespace(max_retries=2)

            def plan(self, context):
                type(self).calls += 1
                return ["search_literature", "parse_paper_bundle", "extract_paper_notes", "build_related_work_matrix"]

        class _Researcher:
            calls = 0

            def __init__(self, *, context, state):
                self.state = state

            def execute_plan(self, skill_ids, artifacts):
                type(self).calls += 1
                output = list(artifacts) + [
                    _artifact("CorpusSnapshot", {"papers": [], "web_sources": [], "indexed_paper_ids": []}),
                    _artifact("RelatedWorkMatrix", {"narrative": f"n{type(self).calls}", "claims": []}),
                    _artifact("GapMap", {"gaps": [f"gap-{type(self).calls}"]}),
                ]
                self.state["_artifact_objects"] = output
                self.state["analyses"] = []
                self.state["findings"] = [f"finding-{type(self).calls}"]
                self.state["gaps"] = [f"gap-{type(self).calls}"]
                self.state["synthesis"] = f"n{type(self).calls}"
                return output

        class _Experimenter:
            calls = 0

            def __init__(self, *, context, state):
                self.state = state

            def design(self, artifacts):
                type(self).calls += 1
                output = list(artifacts) + [
                    _artifact("ExperimentPlan", {"rq_experiments": [{"research_question": "rq"}]}),
                    _artifact(
                        "ExperimentResults",
                        {"status": "validated", "runs": [{"run_id": "run-1", "research_question": "rq", "metrics": []}]},
                    ),
                ]
                self.state["_artifact_objects"] = output
                self.state["experiment_plan"] = {"rq_experiments": [{"research_question": "rq"}]}
                self.state["experiment_results"] = {
                    "status": "validated",
                    "runs": [{"run_id": "run-1", "research_question": "rq", "metrics": []}],
                }
                self.state["await_experiment_results"] = False
                return output

        class _Analyst:
            calls = 0

            def __init__(self, *, context, state):
                self.state = state

            def analyze(self, artifacts):
                type(self).calls += 1
                output = list(artifacts) + [
                    _artifact("ExperimentAnalysis", {"summary": "analysis"}),
                    _artifact("PerformanceMetrics", {"validated": True}),
                ]
                self.state["_artifact_objects"] = output
                self.state["result_analysis"] = {"summary": "analysis"}
                self.state["performance_metrics"] = {"validated": True}
                return output

        class _Writer:
            calls = 0

            def __init__(self, *, context, state):
                self.state = state

            def write(self, artifacts):
                type(self).calls += 1
                output = list(artifacts) + [_artifact("ResearchReport", {"report": f"report-{type(self).calls}"})]
                self.state["_artifact_objects"] = output
                self.state["report"] = {"report": f"report-{type(self).calls}"}
                return output

        class _Critic:
            calls = 0

            def __init__(self, *, context, state):
                self.state = state

            def evaluate(self, artifacts):
                type(self).calls += 1
                action = "retry_upstream" if type(self).calls == 1 else "continue"
                return (
                    "revise" if type(self).calls == 1 else "pass",
                    _artifact("CritiqueReport", {"verdict": {"action": action}, "details": {"suggested_queries": ["q2"]}}),
                )

        with patch("src.agent.runtime.orchestrator.ensure_plugins_registered"):
            with patch("src.agent.runtime.orchestrator.ConductorAgent", _Conductor):
                with patch("src.agent.runtime.orchestrator.ResearcherAgent", _Researcher):
                    with patch("src.agent.runtime.orchestrator.ExperimenterAgent", _Experimenter):
                        with patch("src.agent.runtime.orchestrator.AnalystAgent", _Analyst):
                            with patch("src.agent.runtime.orchestrator.WriterAgent", _Writer):
                                with patch("src.agent.runtime.orchestrator.CriticAgent", _Critic):
                                    orchestrator = ResearchOrchestrator(cfg={"llm": {"provider": "gemini"}}, root=".")
                                    state = orchestrator.run(
                                        topic="topic",
                                        route_roles=["conductor", "researcher", "experimenter", "analyst", "writer", "critic"],
                                    )

        self.assertEqual(state["status"], "Research OS orchestration completed")
        self.assertEqual(state["iteration"], 1)
        self.assertEqual(state["report"]["report"], "report-1")
        self.assertEqual(_Conductor.calls, 2)
        self.assertEqual(_Researcher.calls, 2)
        self.assertEqual(_Critic.calls, 2)
        self.assertEqual(_Experimenter.calls, 1)
        self.assertEqual(_Analyst.calls, 1)
        self.assertEqual(_Writer.calls, 1)

    def test_orchestrator_pauses_after_experimenter_requests_hitl(self) -> None:
        class _Conductor:
            def __init__(self, *, context, state):
                self.policy = SimpleNamespace(max_retries=1)

            def plan(self, context):
                return ["search_literature"]

        class _Researcher:
            def __init__(self, *, context, state):
                self.state = state

            def execute_plan(self, skill_ids, artifacts):
                output = list(artifacts) + [
                    _artifact("CorpusSnapshot", {"papers": [], "web_sources": [], "indexed_paper_ids": []}),
                    _artifact("RelatedWorkMatrix", {"narrative": "narrative", "claims": []}),
                    _artifact("GapMap", {"gaps": ["g1"]}),
                ]
                self.state["_artifact_objects"] = output
                self.state["synthesis"] = "narrative"
                return output

        class _Experimenter:
            def __init__(self, *, context, state):
                self.state = state

            def design(self, artifacts):
                output = list(artifacts) + [
                    _artifact("ExperimentPlan", {"rq_experiments": [{"research_question": "rq"}]}),
                    _artifact(
                        "ExperimentResults",
                        {"status": "pending", "runs": [], "summaries": [], "validation_issues": []},
                    ),
                ]
                self.state["_artifact_objects"] = output
                self.state["experiment_plan"] = {"rq_experiments": [{"research_question": "rq"}]}
                self.state["experiment_results"] = {
                    "status": "pending",
                    "runs": [],
                    "summaries": [],
                    "validation_issues": [],
                }
                self.state["await_experiment_results"] = True
                return output

        class _Analyst:
            def __init__(self, *, context, state):
                self.state = state

            def analyze(self, artifacts):
                raise AssertionError("Analyst should not run while awaiting experiment results")

        class _Writer:
            def __init__(self, *, context, state):
                self.state = state

            def write(self, artifacts):
                raise AssertionError("Writer should not run while awaiting experiment results")

        class _Critic:
            def __init__(self, *, context, state):
                self.state = state

            def evaluate(self, artifacts):
                return "pass", _artifact("CritiqueReport", {"verdict": {"action": "continue"}, "details": {}})

        with patch("src.agent.runtime.orchestrator.ensure_plugins_registered"):
            with patch("src.agent.runtime.orchestrator.ConductorAgent", _Conductor):
                with patch("src.agent.runtime.orchestrator.ResearcherAgent", _Researcher):
                    with patch("src.agent.runtime.orchestrator.ExperimenterAgent", _Experimenter):
                        with patch("src.agent.runtime.orchestrator.AnalystAgent", _Analyst):
                            with patch("src.agent.runtime.orchestrator.WriterAgent", _Writer):
                                with patch("src.agent.runtime.orchestrator.CriticAgent", _Critic):
                                    orchestrator = ResearchOrchestrator(cfg={"llm": {"provider": "gemini"}}, root=".")
                                    state = orchestrator.run(
                                        topic="topic",
                                        route_roles=["conductor", "researcher", "experimenter", "analyst", "writer", "critic"],
                                    )

        self.assertEqual(state["status"], "Research OS orchestration paused for HITL")
        self.assertTrue(state["await_experiment_results"])
        self.assertEqual(state["role_status"]["experimenter"], "completed")
        self.assertEqual(state["role_status"]["analyst"], "waiting")
        self.assertEqual(state["role_status"]["writer"], "waiting")
        artifact_types = [artifact["artifact_type"] for artifact in state["artifacts"]]
        self.assertIn("ExperimentPlan", artifact_types)
        self.assertIn("ExperimentResults", artifact_types)

    def test_orchestrator_stops_when_budget_exceeded(self) -> None:
        with patch("src.agent.runtime.orchestrator.ensure_plugins_registered"):
            with patch("src.agent.runtime.orchestrator.budget_guard_allows", return_value=(False, "budget exceeded")):
                orchestrator = ResearchOrchestrator(cfg={"llm": {"provider": "gemini"}}, root=".")
                state = orchestrator.run(topic="topic")
        self.assertEqual(state["status"], "budget exceeded")
        self.assertEqual(state["error"], "budget exceeded")

    def test_orchestrator_review_only_request_skips_experiment_roles(self) -> None:
        class _Conductor:
            def __init__(self, *, context, state):
                self.policy = SimpleNamespace(max_retries=1)

            def plan(self, context):
                return ["search_literature"]

        class _Researcher:
            def __init__(self, *, context, state):
                self.state = state

            def execute_plan(self, skill_ids, artifacts):
                output = list(artifacts) + [
                    _artifact("CorpusSnapshot", {"papers": [], "web_sources": [], "indexed_paper_ids": []}),
                    _artifact("RelatedWorkMatrix", {"narrative": "review narrative", "claims": []}),
                    _artifact("GapMap", {"gaps": []}),
                ]
                self.state["_artifact_objects"] = output
                self.state["synthesis"] = "review narrative"
                self.state["analyses"] = []
                self.state["findings"] = []
                return output

        class _Experimenter:
            def __init__(self, *, context, state):
                self.state = state

            def design(self, artifacts):
                raise AssertionError("Experimenter should not run for literature-review-only routing")

        class _Analyst:
            def __init__(self, *, context, state):
                self.state = state

            def analyze(self, artifacts):
                raise AssertionError("Analyst should not run for literature-review-only routing")

        class _Writer:
            def __init__(self, *, context, state):
                self.state = state

            def write(self, artifacts):
                output = list(artifacts) + [_artifact("ResearchReport", {"report": "review only report"})]
                self.state["_artifact_objects"] = output
                self.state["report"] = {"report": "review only report"}
                return output

        class _Critic:
            def __init__(self, *, context, state):
                self.state = state

            def evaluate(self, artifacts):
                return "pass", _artifact("CritiqueReport", {"verdict": {"action": "continue"}, "details": {}})

        with patch("src.agent.runtime.orchestrator.ensure_plugins_registered"):
            with patch("src.agent.runtime.orchestrator.ConductorAgent", _Conductor):
                with patch("src.agent.runtime.orchestrator.ResearcherAgent", _Researcher):
                    with patch("src.agent.runtime.orchestrator.ExperimenterAgent", _Experimenter):
                        with patch("src.agent.runtime.orchestrator.AnalystAgent", _Analyst):
                            with patch("src.agent.runtime.orchestrator.WriterAgent", _Writer):
                                with patch("src.agent.runtime.orchestrator.CriticAgent", _Critic):
                                    with patch(
                                        "src.agent.runtime.orchestrator.resolve_route_plan",
                                        return_value={
                                            "mode": "literature_review_only",
                                            "nodes": ["conductor", "researcher", "writer", "critic"],
                                            "rationale": ["Using mocked literature-review-only route."],
                                            "edges": [],
                                        },
                                    ):
                                        orchestrator = ResearchOrchestrator(cfg={"llm": {"provider": "gemini"}}, root=".")
                                        state = orchestrator.run(
                                            topic="topic",
                                            user_request="Please do a literature review only.",
                                        )

        self.assertEqual(state["route_mode"], "literature_review_only")
        self.assertEqual(state["role_status"]["experimenter"], "skipped")
        self.assertEqual(state["role_status"]["analyst"], "skipped")
        self.assertEqual(state["role_status"]["writer"], "completed")
        self.assertEqual(state["report"]["report"], "review only report")

    def test_orchestrator_explicit_writer_only_route(self) -> None:
        class _Conductor:
            def __init__(self, *, context, state):
                self.policy = SimpleNamespace(max_retries=1)

            def plan(self, context):
                raise AssertionError("Conductor should not run for explicit writer-only routing")

        class _Researcher:
            def __init__(self, *, context, state):
                self.state = state

            def execute_plan(self, skill_ids, artifacts):
                raise AssertionError("Researcher should not run for explicit writer-only routing")

        class _Experimenter:
            def __init__(self, *, context, state):
                self.state = state

            def design(self, artifacts):
                raise AssertionError("Experimenter should not run for explicit writer-only routing")

        class _Analyst:
            def __init__(self, *, context, state):
                self.state = state

            def analyze(self, artifacts):
                raise AssertionError("Analyst should not run for explicit writer-only routing")

        class _Writer:
            def __init__(self, *, context, state):
                self.state = state

            def write(self, artifacts):
                output = list(artifacts) + [_artifact("ResearchReport", {"report": "writer only"})]
                self.state["_artifact_objects"] = output
                self.state["report"] = {"report": "writer only"}
                return output

        class _Critic:
            def __init__(self, *, context, state):
                self.state = state

            def evaluate(self, artifacts):
                raise AssertionError("Critic should not run for explicit writer-only routing")

        with patch("src.agent.runtime.orchestrator.ensure_plugins_registered"):
            with patch("src.agent.runtime.orchestrator.ConductorAgent", _Conductor):
                with patch("src.agent.runtime.orchestrator.ResearcherAgent", _Researcher):
                    with patch("src.agent.runtime.orchestrator.ExperimenterAgent", _Experimenter):
                        with patch("src.agent.runtime.orchestrator.AnalystAgent", _Analyst):
                            with patch("src.agent.runtime.orchestrator.WriterAgent", _Writer):
                                with patch("src.agent.runtime.orchestrator.CriticAgent", _Critic):
                                    orchestrator = ResearchOrchestrator(cfg={"llm": {"provider": "gemini"}}, root=".")
                                    state = orchestrator.run(
                                        topic="topic",
                                        user_request="write report only",
                                        route_roles=["writer"],
                                    )

        self.assertEqual(state["route_mode"], "explicit_roles")
        self.assertEqual(state["role_status"]["conductor"], "skipped")
        self.assertEqual(state["role_status"]["researcher"], "skipped")
        self.assertEqual(state["role_status"]["critic"], "skipped")
        self.assertEqual(state["role_status"]["writer"], "completed")
        self.assertEqual(state["report"]["report"], "writer only")
