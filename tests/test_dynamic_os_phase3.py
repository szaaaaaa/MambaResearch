from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import app
from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.observation import ErrorType, NodeStatus
from src.dynamic_os.contracts.policy import BudgetPolicy, PermissionPolicy
from src.dynamic_os.contracts.route_plan import PlanNode, RoleId, RoutePlan
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput
from src.dynamic_os.contracts.skill_spec import SkillSpec
from src.dynamic_os.executor import Executor, NodeRunner
from src.dynamic_os.planner import Planner, PlannerOutputError, assess_review_need, decide_termination
from src.dynamic_os.planner.prompts import build_planner_messages
from src.dynamic_os.policy.engine import PolicyEngine
from src.dynamic_os.roles.registry import RoleRegistry
from src.dynamic_os.skills.registry import SkillRegistry
from src.dynamic_os.storage.memory import InMemoryArtifactStore, InMemoryObservationStore, InMemoryPlanStore
from src.dynamic_os.tools.gateway import ToolGateway
from src.dynamic_os.tools.registry import ToolCapability, ToolRegistry
from src.server.settings import RUN_EVENT_PREFIX, RUN_STATE_PREFIX

BUILTINS_DIR = Path(__file__).resolve().parents[1] / "src" / "dynamic_os" / "skills" / "builtins"


class FakePlannerModel:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def generate(self, messages, response_schema):
        self.calls += 1
        return self._responses.pop(0)


class FakeSkillRegistry:
    def __init__(self, specs: list[SkillSpec], runners: dict[str, object] | None = None) -> None:
        runner_map = runners or {}
        self._loaded = [
            SimpleNamespace(spec=spec, runner=runner_map.get(spec.id, _default_skill_runner(spec.id)))
            for spec in specs
        ]
        self._by_id = {item.spec.id: item for item in self._loaded}

    def list(self):
        return list(self._loaded)

    def get(self, skill_id):
        return self._by_id[skill_id]

    def validate_role_assignment(self, role_id, skill_ids, role_registry):
        loaded = {item.spec.id: item.spec for item in self._loaded}
        missing = [skill_id for skill_id in skill_ids if skill_id not in loaded]
        if missing:
            raise ValueError(f"unknown skills for role {role_id}: {', '.join(missing)}")
        role_registry.validate_skill_allowlist(role_id, skill_ids)
        incompatible = [
            skill_id
            for skill_id in skill_ids
            if role_registry.get(role_id).id not in loaded[skill_id].applicable_roles
        ]
        if incompatible:
            raise ValueError(f"role {role_id} is not applicable for skills: {', '.join(incompatible)}")


def _planner_with_model(model: FakePlannerModel, skill_specs: list[SkillSpec]) -> Planner:
    return Planner(
        model=model,
        role_registry=RoleRegistry.from_file(),
        skill_registry=FakeSkillRegistry(skill_specs),
        artifact_store=InMemoryArtifactStore(),
        observation_store=InMemoryObservationStore(),
        plan_store=InMemoryPlanStore(),
    )


def _default_skill_runner(skill_id: str):
    async def runner(ctx):
        return SkillOutput(success=True)

    return runner


def _skill_spec(
    skill_id: str,
    roles: list[str],
    *,
    permissions: dict | None = None,
    allowed_tools: list[str] | None = None,
) -> SkillSpec:
    return SkillSpec.model_validate(
        {
            "id": skill_id,
            "name": skill_id.replace("_", " ").title(),
            "applicable_roles": roles,
            "description": skill_id,
            "input_contract": {"required": []},
            "output_artifacts": [],
            "allowed_tools": allowed_tools or [],
            "permissions": permissions or {},
            "timeout_sec": 60,
        }
    )


def _plan_json(role: str, skill_id: str, *, needs_review: bool = False) -> str:
    return json.dumps(
        {
            "run_id": "run_1",
            "planning_iteration": 0,
            "horizon": 1,
            "nodes": [
                {
                    "node_id": "node_research_1",
                    "role": role,
                    "goal": "Collect papers",
                    "inputs": [],
                    "allowed_skills": [skill_id],
                    "success_criteria": ["at_least_one_source"],
                    "failure_policy": "replan",
                    "expected_outputs": ["SourceSet"],
                    "needs_review": needs_review,
                }
            ],
            "edges": [],
            "planner_notes": [],
            "terminate": False,
        }
    )


def _route_plan(run_id: str, planning_iteration: int, role: str, skill_id: str, *, terminate: bool = False, failure_policy: str = "replan") -> RoutePlan:
    return RoutePlan(
        run_id=run_id,
        planning_iteration=planning_iteration,
        horizon=1,
        nodes=[
            PlanNode(
                node_id="node_research_1",
                role=role,
                goal="Collect papers",
                allowed_skills=[skill_id],
                expected_outputs=["SourceSet"] if skill_id == "search_papers" else [],
                failure_policy=failure_policy,
            )
        ],
        terminate=terminate,
    )


def _phase5_artifact(
    artifact_id: str,
    artifact_type: str,
    *,
    role: RoleId,
    skill: str,
    payload: dict | None = None,
) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        producer_role=role,
        producer_skill=skill,
        payload=payload or {},
    )


def _phase5_inputs(skill_id: str) -> list[ArtifactRecord]:
    if skill_id == "search_papers":
        return [
            _phase5_artifact(
                "search_plan_1",
                "SearchPlan",
                role=RoleId.conductor,
                skill="plan_research",
                payload={"search_queries": ["retrieval planning"]},
            )
        ]
    if skill_id == "fetch_fulltext":
        return [
            _phase5_artifact(
                "source_set_1",
                "SourceSet",
                role=RoleId.researcher,
                skill="search_papers",
                payload={
                    "query": "retrieval planning",
                    "sources": [{"paper_id": "paper_a", "title": "Paper A", "abstract": "A paper"}],
                },
            )
        ]
    if skill_id == "extract_notes":
        return [
            _phase5_artifact(
                "source_set_2",
                "SourceSet",
                role=RoleId.researcher,
                skill="fetch_fulltext",
                payload={
                    "sources": [
                        {
                            "paper_id": "paper_a",
                            "title": "Paper A",
                            "content": "Full text for Paper A",
                        }
                    ]
                },
            )
        ]
    if skill_id == "build_evidence_map":
        return [
            _phase5_artifact(
                "paper_notes_1",
                "PaperNotes",
                role=RoleId.researcher,
                skill="extract_notes",
                payload={"notes": [{"source_id": "paper_a", "summary": "Strong retrieval baseline."}]},
            )
        ]
    if skill_id == "design_experiment":
        return [
            _phase5_artifact(
                "evidence_map_1",
                "EvidenceMap",
                role=RoleId.researcher,
                skill="build_evidence_map",
                payload={"summary": "Need a stronger retrieval comparison."},
            )
        ]
    if skill_id == "run_experiment":
        return [
            _phase5_artifact(
                "experiment_plan_1",
                "ExperimentPlan",
                role=RoleId.experimenter,
                skill="design_experiment",
                payload={
                    "language": "python",
                    "code": "metrics = {'accuracy': 0.91, 'latency_ms': 120}\nprint(metrics)",
                },
            )
        ]
    if skill_id == "analyze_metrics":
        return [
            _phase5_artifact(
                "experiment_results_1",
                "ExperimentResults",
                role=RoleId.experimenter,
                skill="run_experiment",
                payload={
                    "status": "completed",
                    "metrics": {"accuracy": 0.91, "latency_ms": 120},
                },
            )
        ]
    if skill_id == "draft_report":
        return [
            _phase5_artifact(
                "evidence_map_2",
                "EvidenceMap",
                role=RoleId.researcher,
                skill="build_evidence_map",
                payload={"summary": "Evidence favors the retrieval-planning approach."},
            )
        ]
    if skill_id == "review_artifact":
        return [
            _phase5_artifact(
                "report_1",
                "ResearchReport",
                role=RoleId.writer,
                skill="draft_report",
                payload={"report": "A concise final report."},
            )
        ]
    return []


def _phase5_gateway(*, event_sink=None, policy: PolicyEngine | None = None) -> ToolGateway:
    registry = ToolRegistry.from_servers(
        [
            {"server_id": "llm", "tools": [{"name": "chat", "capability": "llm_chat"}]},
            {"server_id": "search", "tools": [{"name": "papers", "capability": "search"}]},
            {
                "server_id": "retrieval",
                "tools": [
                    {"name": "store", "capability": "retrieve"},
                    {"name": "indexer", "capability": "index"},
                ],
            },
            {"server_id": "exec", "tools": [{"name": "execute_code", "capability": "execute_code"}]},
        ]
    )
    engine = policy or PolicyEngine(permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())]))

    async def invoker(tool, payload):
        if tool.capability == ToolCapability.llm_chat:
            user_message = next(
                (
                    message.get("content", "")
                    for message in reversed(payload.get("messages", []))
                    if message.get("role") == "user"
                ),
                "",
            )
            return f"LLM summary: {user_message[:120]}"
        if tool.capability == ToolCapability.search:
            query = str(payload.get("query") or "")
            return [
                {
                    "paper_id": "paper_a",
                    "title": f"Paper A on {query}",
                    "abstract": "High-signal retrieval planning paper.",
                    "url": "https://example.com/paper-a",
                }
            ]
        if tool.capability == ToolCapability.retrieve:
            query = str(payload.get("query") or "")
            return [
                {
                    "paper_id": "paper_a",
                    "title": "Paper A",
                    "content": f"Full text for {query}",
                }
            ]
        if tool.capability == ToolCapability.index:
            return []
        raise AssertionError(f"unexpected capability: {tool.capability.value}")

    def code_executor(*, code: str, language: str, timeout_sec: int):
        return {
            "exit_code": 0,
            "language": language,
            "timeout_sec": timeout_sec,
            "stdout": code,
            "metrics": {"accuracy": 0.91, "latency_ms": 120},
        }

    return ToolGateway(
        registry=registry,
        policy=engine,
        mcp_invoker=invoker,
        code_executor=code_executor,
        event_sink=event_sink,
    )


def test_planner_accepts_valid_plan_and_reviewer_is_optional() -> None:
    planner = _planner_with_model(
        FakePlannerModel([_plan_json("researcher", "search_papers")]),
        [_skill_spec("search_papers", ["researcher"])],
    )

    plan = asyncio.run(planner.plan(user_request="Find papers about retrieval planning", planning_iteration=0))

    assert isinstance(plan, RoutePlan)
    assert [node.role.value for node in plan.nodes] == ["researcher"]


def test_planner_retries_once_after_invalid_output() -> None:
    model = FakePlannerModel(
        [
            '{"run_id": "bad"}',
            _plan_json("researcher", "search_papers"),
        ]
    )
    planner = _planner_with_model(model, [_skill_spec("search_papers", ["researcher"])])

    plan = asyncio.run(planner.plan(user_request="Find papers", planning_iteration=0))

    assert plan.nodes[0].allowed_skills == ["search_papers"]
    assert model.calls == 2


def test_planner_raises_after_second_invalid_output() -> None:
    model = FakePlannerModel(['{"run_id": "bad"}', '{"run_id": "still_bad"}'])
    planner = _planner_with_model(model, [_skill_spec("search_papers", ["researcher"])])

    with pytest.raises(PlannerOutputError):
        asyncio.run(planner.plan(user_request="Find papers", planning_iteration=0))

    assert model.calls == 2


def test_planner_accepts_inserted_reviewer_node() -> None:
    planner = _planner_with_model(
        FakePlannerModel([_plan_json("reviewer", "review_artifact", needs_review=True)]),
        [_skill_spec("review_artifact", ["reviewer"])],
    )

    plan = asyncio.run(planner.plan(user_request="Review the final report", planning_iteration=0))

    assert plan.nodes[0].role.value == "reviewer"
    assert plan.nodes[0].needs_review is True


def test_planner_rejects_unloaded_skills() -> None:
    planner = _planner_with_model(
        FakePlannerModel(
            [
                _plan_json("researcher", "search_papers"),
                _plan_json("researcher", "search_papers"),
            ]
        ),
        [],
    )

    with pytest.raises(PlannerOutputError):
        asyncio.run(planner.plan(user_request="Find papers", planning_iteration=0))


def test_planner_prompt_only_exposes_loaded_allowlisted_skills() -> None:
    planner = _planner_with_model(
        FakePlannerModel([_plan_json("researcher", "search_papers")]),
        [
            _skill_spec("search_papers", ["researcher"]),
            _skill_spec("custom_search", ["researcher"]),
        ],
    )

    messages = build_planner_messages(
        user_request="Find papers",
        role_registry=RoleRegistry.from_file(),
        available_skills_by_role=planner._available_skills_by_role(),
        artifact_summary=[],
        observation_summary=[],
        budget_snapshot={},
        planning_iteration=0,
    )

    assert "search_papers" in messages[0]["content"]
    assert "custom_search" not in messages[0]["content"]


def test_planner_meta_skills_cover_review_and_termination() -> None:
    assert assess_review_need() is False
    assert assess_review_need(critical_deliverable=True) is True
    assert decide_termination([{"artifact_type": "ResearchReport"}]) is True
    assert decide_termination([{"artifact_type": "SourceSet"}]) is False


class SequencePlanner:
    def __init__(self, plans: list[RoutePlan]) -> None:
        self._plans = list(plans)
        self.calls = 0

    async def plan(self, *, user_request: str, planning_iteration: int, budget_snapshot=None) -> RoutePlan:
        self.calls += 1
        return self._plans.pop(0)


def test_executor_runs_local_loop_and_emits_events() -> None:
    role_registry = RoleRegistry.from_file()
    artifact_store = InMemoryArtifactStore()
    observation_store = InMemoryObservationStore()
    plan_store = InMemoryPlanStore()
    events: list[object] = []

    async def search_runner(ctx):
        results = await ctx.tools.search("retrieval planning", source="arxiv", max_results=2)
        assert results[0]["title"] == "Paper A"
        return SkillOutput(
            success=True,
            output_artifacts=[
                ArtifactRecord(
                    artifact_id="ss_1",
                    artifact_type="SourceSet",
                    producer_role=RoleId.researcher,
                    producer_skill="search_papers",
                )
            ],
        )

    skill_registry = FakeSkillRegistry(
        [
            _skill_spec(
                "search_papers",
                ["researcher"],
                permissions={"network": True},
                allowed_tools=["mcp.search.arxiv"],
            )
        ],
        runners={"search_papers": search_runner},
    )
    policy = PolicyEngine(permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())]))
    tools = ToolGateway(
        registry=ToolRegistry.from_servers(
            [{"server_id": "search", "tools": [{"name": "arxiv", "capability": "search"}]}]
        ),
        policy=policy,
        mcp_invoker=lambda tool, payload: [{"title": "Paper A", "tool_id": tool.tool_id}],
        event_sink=events.append,
    )
    node_runner = NodeRunner(
        role_registry=role_registry,
        skill_registry=skill_registry,
        artifact_store=artifact_store,
        observation_store=observation_store,
        tools=tools,
        policy=policy,
        event_sink=events.append,
    )
    planner = SequencePlanner(
        [
            _route_plan("run_exec", 0, "researcher", "search_papers"),
            _route_plan("run_exec", 1, "researcher", "search_papers", terminate=True),
        ]
    )
    executor = Executor(
        planner=planner,
        node_runner=node_runner,
        artifact_store=artifact_store,
        observation_store=observation_store,
        policy=policy,
        event_sink=events.append,
    )

    result = asyncio.run(executor.run(user_request="Find papers", run_id="run_exec"))

    assert planner.calls == 2
    assert result.final_artifacts == ["artifact:SourceSet:ss_1"]
    assert observation_store.list_latest()[-1].status == NodeStatus.success
    event_types = [event.type for event in events]
    assert "plan_update" in event_types
    assert "node_status" in event_types
    assert "skill_invoke" in event_types
    assert "tool_invoke" in event_types
    assert "artifact_created" in event_types
    assert "observation" in event_types
    assert event_types[-1] == "run_terminate"


def test_executor_returns_observation_and_replans_on_failure() -> None:
    role_registry = RoleRegistry.from_file()
    artifact_store = InMemoryArtifactStore()
    observation_store = InMemoryObservationStore()
    events: list[object] = []

    async def failing_runner(ctx):
        return SkillOutput(success=False, error="rate limited")

    skill_registry = FakeSkillRegistry(
        [_skill_spec("search_papers", ["researcher"])],
        runners={"search_papers": failing_runner},
    )
    policy = PolicyEngine(permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())]))
    tools = ToolGateway(
        registry=ToolRegistry.from_servers(
            [{"server_id": "search", "tools": [{"name": "arxiv", "capability": "search"}]}]
        ),
        policy=policy,
        mcp_invoker=lambda tool, payload: [],
        event_sink=events.append,
    )
    node_runner = NodeRunner(
        role_registry=role_registry,
        skill_registry=skill_registry,
        artifact_store=artifact_store,
        observation_store=observation_store,
        tools=tools,
        policy=policy,
        event_sink=events.append,
    )
    planner = SequencePlanner(
        [
            _route_plan("run_fail", 0, "researcher", "search_papers", failure_policy="replan"),
            _route_plan("run_fail", 1, "researcher", "search_papers", terminate=True),
        ]
    )
    executor = Executor(
        planner=planner,
        node_runner=node_runner,
        artifact_store=artifact_store,
        observation_store=observation_store,
        policy=policy,
        event_sink=events.append,
    )

    result = asyncio.run(executor.run(user_request="Find papers", run_id="run_fail"))

    latest_observation = observation_store.list_latest()[-1]
    assert latest_observation.status == NodeStatus.needs_replan
    assert latest_observation.error_type == ErrorType.skill_error
    assert any(event.type == "replan" for event in events)
    assert result.termination_reason == "planner_terminated"


def test_executor_terminates_on_budget_exhaustion() -> None:
    role_registry = RoleRegistry.from_file()
    artifact_store = InMemoryArtifactStore()
    observation_store = InMemoryObservationStore()
    events: list[object] = []

    skill_registry = FakeSkillRegistry([_skill_spec("search_papers", ["researcher"])])
    policy = PolicyEngine(
        budget_policy=BudgetPolicy(max_planning_iterations=1),
        permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())]),
    )
    tools = ToolGateway(
        registry=ToolRegistry.from_servers(
            [{"server_id": "search", "tools": [{"name": "arxiv", "capability": "search"}]}]
        ),
        policy=policy,
        mcp_invoker=lambda tool, payload: [],
        event_sink=events.append,
    )
    node_runner = NodeRunner(
        role_registry=role_registry,
        skill_registry=skill_registry,
        artifact_store=artifact_store,
        observation_store=observation_store,
        tools=tools,
        policy=policy,
        event_sink=events.append,
    )
    planner = SequencePlanner(
        [
            _route_plan("run_budget", 0, "researcher", "search_papers"),
            _route_plan("run_budget", 1, "researcher", "search_papers", terminate=True),
        ]
    )
    executor = Executor(
        planner=planner,
        node_runner=node_runner,
        artifact_store=artifact_store,
        observation_store=observation_store,
        policy=policy,
        event_sink=events.append,
    )

    result = asyncio.run(executor.run(user_request="Find papers", run_id="run_budget"))

    assert result.termination_reason == "planning iteration budget exceeded"
    assert events[-1].type == "run_terminate"


def test_executor_selects_matching_skill_from_allowed_skills() -> None:
    role_registry = RoleRegistry.from_file()
    artifact_store = InMemoryArtifactStore()
    observation_store = InMemoryObservationStore()
    skill_registry = SkillRegistry.discover([BUILTINS_DIR])
    policy = PolicyEngine(permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())]))
    artifact_store.save(
        ArtifactRecord(
            artifact_id="ss_1",
            artifact_type="SourceSet",
            producer_role=RoleId.researcher,
            producer_skill="search_papers",
            payload={
                "sources": [
                    {
                        "paper_id": "paper_a",
                        "title": "Paper A",
                        "content": "Full text for Paper A",
                    }
                ]
            },
        )
    )
    node_runner = NodeRunner(
        role_registry=role_registry,
        skill_registry=skill_registry,
        artifact_store=artifact_store,
        observation_store=observation_store,
        tools=_phase5_gateway(policy=policy),
        policy=policy,
    )

    result = asyncio.run(
        node_runner.run_node(
            run_id="run_select",
            node=PlanNode(
                node_id="node_research_1",
                role=RoleId.researcher,
                goal="Extract notes from fetched sources",
                inputs=["artifact:SourceSet:ss_1"],
                allowed_skills=["search_papers", "extract_notes"],
                expected_outputs=["PaperNotes"],
            ),
        )
    )

    assert result.skill_id == "extract_notes"
    assert result.observation.status == NodeStatus.success
    assert [artifact.artifact_type for artifact in result.artifacts] == ["PaperNotes"]


def test_executor_rejects_planner_run_id_mismatch() -> None:
    role_registry = RoleRegistry.from_file()
    artifact_store = InMemoryArtifactStore()
    observation_store = InMemoryObservationStore()
    policy = PolicyEngine(permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())]))
    planner = SequencePlanner(
        [
            RoutePlan(
                run_id="wrong_run",
                planning_iteration=0,
                horizon=1,
                nodes=[
                    PlanNode(
                        node_id="node_writer_1",
                        role=RoleId.writer,
                        goal="Draft final report",
                        allowed_skills=["draft_report"],
                    )
                ],
                terminate=True,
            )
        ]
    )
    executor = Executor(
        planner=planner,
        node_runner=NodeRunner(
            role_registry=role_registry,
            skill_registry=SkillRegistry.discover([BUILTINS_DIR]),
            artifact_store=artifact_store,
            observation_store=observation_store,
            tools=_phase5_gateway(policy=policy),
            policy=policy,
        ),
        artifact_store=artifact_store,
        observation_store=observation_store,
        policy=policy,
    )

    result = asyncio.run(executor.run(user_request="Draft report", run_id="run_expected"))

    assert "run_id mismatch" in result.termination_reason


@pytest.mark.parametrize(
    ("skill_id", "role_id", "expected_types"),
    [
        ("plan_research", "conductor", {"TopicBrief", "SearchPlan"}),
        ("search_papers", "researcher", {"SourceSet"}),
        ("fetch_fulltext", "researcher", {"SourceSet"}),
        ("extract_notes", "researcher", {"PaperNotes"}),
        ("build_evidence_map", "researcher", {"EvidenceMap", "GapMap"}),
        ("design_experiment", "experimenter", {"ExperimentPlan"}),
        ("run_experiment", "experimenter", {"ExperimentResults"}),
        ("analyze_metrics", "analyst", {"ExperimentAnalysis", "PerformanceMetrics"}),
        ("draft_report", "writer", {"ResearchReport"}),
        ("review_artifact", "reviewer", {"ReviewVerdict"}),
    ],
)
def test_phase5_builtin_skills_produce_expected_outputs(
    skill_id: str,
    role_id: str,
    expected_types: set[str],
) -> None:
    registry = SkillRegistry.discover([BUILTINS_DIR])
    loaded = registry.get(skill_id)
    ctx = SkillContext(
        skill_id=skill_id,
        role_id=role_id,
        run_id="run_phase5_unit",
        node_id=f"node_{skill_id}",
        goal="Investigate retrieval planning",
        input_artifacts=_phase5_inputs(skill_id),
        tools=_phase5_gateway(),
    )

    output = asyncio.run(loaded.runner(ctx))

    assert all(tool_id.startswith("mcp.") for tool_id in loaded.spec.allowed_tools)
    assert output.success is True
    assert {artifact.artifact_type for artifact in output.output_artifacts} == expected_types


def test_phase5_run_experiment_returns_failure_on_executor_error() -> None:
    registry = SkillRegistry.discover([BUILTINS_DIR])
    loaded = registry.get("run_experiment")
    policy = PolicyEngine(permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())]))
    ctx = SkillContext(
        skill_id="run_experiment",
        role_id="experimenter",
        run_id="run_phase5_fail",
        node_id="node_run_experiment_1",
        goal="Run the experiment",
        input_artifacts=[
            _phase5_artifact(
                "experiment_plan_fail_1",
                "ExperimentPlan",
                role=RoleId.experimenter,
                skill="design_experiment",
                payload={"language": "python", "code": "raise RuntimeError('boom')"},
            )
        ],
        tools=ToolGateway(
            registry=ToolRegistry.from_servers(
                [{"server_id": "exec", "tools": [{"name": "execute_code", "capability": "execute_code"}]}]
            ),
            policy=policy,
            code_executor=lambda **kwargs: {"exit_code": 1, "stderr": "boom"},
        ),
    )

    output = asyncio.run(loaded.runner(ctx))

    assert output.success is False
    assert "exit_code=1" in (output.error or "")


def test_phase5_end_to_end_research_loop_uses_builtin_skills() -> None:
    artifact_store = InMemoryArtifactStore()
    observation_store = InMemoryObservationStore()
    plan_store = InMemoryPlanStore()
    role_registry = RoleRegistry.from_file()
    skill_registry = SkillRegistry.discover([BUILTINS_DIR])
    events: list[object] = []

    planner = Planner(
        model=FakePlannerModel(
            [
                json.dumps(
                    {
                        "run_id": "run_phase5",
                        "planning_iteration": 0,
                        "horizon": 7,
                        "nodes": [
                            {
                                "node_id": "node_plan_1",
                                "role": "conductor",
                                "goal": "Plan the topic",
                                "inputs": [],
                                "allowed_skills": ["plan_research"],
                                "success_criteria": ["topic_is_scoped"],
                                "failure_policy": "replan",
                                "expected_outputs": ["TopicBrief", "SearchPlan"],
                                "needs_review": False,
                            },
                            {
                                "node_id": "node_search_1",
                                "role": "researcher",
                                "goal": "Search for papers",
                                "inputs": ["artifact:SearchPlan:node_plan_1_search_plan"],
                                "allowed_skills": ["search_papers"],
                                "success_criteria": ["at_least_one_source"],
                                "failure_policy": "replan",
                                "expected_outputs": ["SourceSet"],
                                "needs_review": False,
                            },
                            {
                                "node_id": "node_fetch_1",
                                "role": "researcher",
                                "goal": "Fetch fuller text",
                                "inputs": ["artifact:SourceSet:node_search_1_source_set"],
                                "allowed_skills": ["fetch_fulltext"],
                                "success_criteria": ["sources_enriched"],
                                "failure_policy": "replan",
                                "expected_outputs": ["SourceSet"],
                                "needs_review": False,
                            },
                            {
                                "node_id": "node_notes_1",
                                "role": "researcher",
                                "goal": "Extract notes",
                                "inputs": ["artifact:SourceSet:node_fetch_1_source_set"],
                                "allowed_skills": ["extract_notes"],
                                "success_criteria": ["notes_created"],
                                "failure_policy": "replan",
                                "expected_outputs": ["PaperNotes"],
                                "needs_review": False,
                            },
                            {
                                "node_id": "node_evidence_1",
                                "role": "researcher",
                                "goal": "Build evidence map",
                                "inputs": ["artifact:PaperNotes:node_notes_1_paper_notes"],
                                "allowed_skills": ["build_evidence_map"],
                                "success_criteria": ["evidence_synthesized"],
                                "failure_policy": "replan",
                                "expected_outputs": ["EvidenceMap", "GapMap"],
                                "needs_review": False,
                            },
                            {
                                "node_id": "node_report_1",
                                "role": "writer",
                                "goal": "Draft the final report",
                                "inputs": ["artifact:EvidenceMap:node_evidence_1_evidence_map"],
                                "allowed_skills": ["draft_report"],
                                "success_criteria": ["report_drafted"],
                                "failure_policy": "replan",
                                "expected_outputs": ["ResearchReport"],
                                "needs_review": False,
                            },
                            {
                                "node_id": "node_review_1",
                                "role": "reviewer",
                                "goal": "Review the final report",
                                "inputs": ["artifact:ResearchReport:node_report_1_research_report"],
                                "allowed_skills": ["review_artifact"],
                                "success_criteria": ["review_completed"],
                                "failure_policy": "replan",
                                "expected_outputs": ["ReviewVerdict"],
                                "needs_review": True,
                            },
                        ],
                        "edges": [
                            {"source": "node_plan_1", "target": "node_search_1", "condition": "on_success"},
                            {"source": "node_search_1", "target": "node_fetch_1", "condition": "on_success"},
                            {"source": "node_fetch_1", "target": "node_notes_1", "condition": "on_success"},
                            {"source": "node_notes_1", "target": "node_evidence_1", "condition": "on_success"},
                            {"source": "node_evidence_1", "target": "node_report_1", "condition": "on_success"},
                            {"source": "node_report_1", "target": "node_review_1", "condition": "on_success"},
                        ],
                        "planner_notes": [],
                        "terminate": False,
                    }
                ),
                json.dumps(
                    {
                        "run_id": "run_phase5",
                        "planning_iteration": 1,
                        "horizon": 1,
                        "nodes": [
                            {
                                "node_id": "node_stop_1",
                                "role": "writer",
                                "goal": "Stop after the report loop is complete",
                                "inputs": [],
                                "allowed_skills": ["draft_report"],
                                "success_criteria": [],
                                "failure_policy": "replan",
                                "expected_outputs": ["ResearchReport"],
                                "needs_review": False,
                            }
                        ],
                        "edges": [],
                        "planner_notes": ["terminate after built-in loop completion"],
                        "terminate": True,
                    }
                ),
            ]
        ),
        role_registry=role_registry,
        skill_registry=skill_registry,
        artifact_store=artifact_store,
        observation_store=observation_store,
        plan_store=plan_store,
    )
    policy = PolicyEngine(permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())]))
    tools = _phase5_gateway(event_sink=events.append, policy=policy)
    node_runner = NodeRunner(
        role_registry=role_registry,
        skill_registry=skill_registry,
        artifact_store=artifact_store,
        observation_store=observation_store,
        tools=tools,
        policy=policy,
        event_sink=events.append,
    )
    executor = Executor(
        planner=planner,
        node_runner=node_runner,
        artifact_store=artifact_store,
        observation_store=observation_store,
        policy=policy,
        event_sink=events.append,
    )

    result = asyncio.run(executor.run(user_request="Investigate retrieval planning", run_id="run_phase5"))

    assert result.termination_reason == "planner_terminated"
    assert "artifact:ResearchReport:node_report_1_research_report" in result.final_artifacts
    assert "artifact:ReviewVerdict:node_review_1_review_verdict" in result.final_artifacts
    assert {record.artifact_type for record in artifact_store.list_all()} == {
        "TopicBrief",
        "SearchPlan",
        "SourceSet",
        "PaperNotes",
        "EvidenceMap",
        "GapMap",
        "ResearchReport",
        "ReviewVerdict",
    }
    assert any(event.type == "tool_invoke" for event in events)


def test_phase6_api_run_streams_dynamic_runtime_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.server.routes import runs as runs_route

    async def fake_run(self, *, user_request: str, run_id: str | None = None):
        assert user_request == "dynamic runtime request"
        del run_id
        self._event_sink(
            {
                "type": "plan_update",
                "ts": "2026-03-12T00:00:00Z",
                "run_id": "run_phase6",
                "planning_iteration": 0,
                "plan": {
                    "run_id": "run_phase6",
                    "planning_iteration": 0,
                    "horizon": 1,
                    "nodes": [
                        {
                            "node_id": "node_review_1",
                            "role": "reviewer",
                            "goal": "Review the report",
                            "inputs": [],
                            "allowed_skills": ["review_artifact"],
                            "success_criteria": [],
                            "failure_policy": "replan",
                            "expected_outputs": ["ReviewVerdict"],
                            "needs_review": True,
                        }
                    ],
                    "edges": [],
                    "planner_notes": ["Insert reviewer for critical deliverable."],
                    "terminate": False,
                },
            }
        )
        self._event_sink(
            {
                "type": "policy_block",
                "ts": "2026-03-12T00:00:01Z",
                "run_id": "run_phase6",
                "blocked_action": "mcp.exec.execute_code",
                "reason": "sandbox execution is not allowed",
            }
        )
        return SimpleNamespace(
            run_id="run_phase6",
            status="completed",
            route_plan={
                "run_id": "run_phase6",
                "planning_iteration": 0,
                "horizon": 1,
                "nodes": [
                    {
                        "node_id": "node_review_1",
                        "role": "reviewer",
                        "goal": "Review the report",
                        "inputs": [],
                        "allowed_skills": ["review_artifact"],
                        "success_criteria": [],
                        "failure_policy": "replan",
                        "expected_outputs": ["ReviewVerdict"],
                        "needs_review": True,
                    }
                ],
                "edges": [],
                "planner_notes": ["Insert reviewer for critical deliverable."],
                "terminate": False,
            },
            node_status={"node_review_1": "success"},
            artifacts=[
                {
                    "artifact_id": "review_1",
                    "artifact_type": "ReviewVerdict",
                    "producer_role": "reviewer",
                    "producer_skill": "review_artifact",
                }
            ],
            report_text="# Dynamic report",
        )

    monkeypatch.setattr(runs_route.DynamicResearchRuntime, "run", fake_run)
    client = TestClient(app)
    output_dir = Path(".tmp_phase6_api_test")
    output_dir.mkdir(parents=True, exist_ok=True)

    response = client.post(
        "/api/run",
        json={
            "client_request_id": "req_phase6",
            "runOverrides": {
                "topic": "dynamic runtime request",
                "user_request": "dynamic runtime request",
                "output_dir": str(output_dir),
            },
        },
    )

    assert response.status_code == 200
    assert f'{RUN_EVENT_PREFIX}{{"type": "plan_update"' in response.text
    assert f'{RUN_EVENT_PREFIX}{{"type": "policy_block"' in response.text
    assert f'{RUN_STATE_PREFIX}{{"run_id": "run_phase6"' in response.text
    assert '"node_status": {"node_review_1": "success"}' in response.text
    assert '"artifacts": [{"artifact_id": "review_1"' in response.text
    assert "role_status" not in response.text


def test_phase6_api_rejects_output_dir_outside_workspace() -> None:
    client = TestClient(app)
    outside_dir = Path.cwd().resolve().parent

    response = client.post(
        "/api/run",
        json={
            "client_request_id": "req_phase6_invalid_dir",
            "runOverrides": {
                "topic": "dynamic runtime request",
                "user_request": "dynamic runtime request",
                "output_dir": str(outside_dir),
            },
        },
    )

    assert response.status_code == 400
    assert "output_root must stay within workspace root" in response.text


def test_phase6_api_run_failure_still_emits_final_state(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.server.routes import runs as runs_route

    async def fake_run(self, *, user_request: str, run_id: str | None = None):
        del run_id
        assert user_request == "dynamic runtime failure"
        self._event_sink(
            {
                "type": "plan_update",
                "ts": "2026-03-12T00:00:00Z",
                "run_id": "run_phase6_fail",
                "planning_iteration": 0,
                "plan": {
                    "run_id": "run_phase6_fail",
                    "planning_iteration": 0,
                    "horizon": 1,
                    "nodes": [
                        {
                            "node_id": "node_search_1",
                            "role": "researcher",
                            "goal": "Search for papers",
                            "inputs": [],
                            "allowed_skills": ["search_papers"],
                            "success_criteria": [],
                            "failure_policy": "replan",
                            "expected_outputs": ["SourceSet"],
                            "needs_review": False,
                        }
                    ],
                    "edges": [],
                    "planner_notes": [],
                    "terminate": False,
                },
            }
        )
        raise RuntimeError("boom")

    monkeypatch.setattr(runs_route.DynamicResearchRuntime, "run", fake_run)
    client = TestClient(app)
    output_dir = Path(".tmp_phase6_api_failure")
    output_dir.mkdir(parents=True, exist_ok=True)

    response = client.post(
        "/api/run",
        json={
            "client_request_id": "req_phase6_failure",
            "runOverrides": {
                "topic": "dynamic runtime failure",
                "user_request": "dynamic runtime failure",
                "output_dir": str(output_dir),
            },
        },
    )

    assert response.status_code == 200
    assert f'{RUN_STATE_PREFIX}{{"run_id": "run_phase6_fail", "status": "failed"' in response.text
    assert '"route_plan": {"run_id": "run_phase6_fail"' in response.text


def test_phase6_api_rejects_resume_run_id_even_with_topic() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={
            "client_request_id": "req_phase6_resume",
            "runOverrides": {
                "topic": "dynamic runtime request",
                "user_request": "dynamic runtime request",
                "resume_run_id": "old_run_1",
            },
        },
    )

    assert response.status_code == 400
    assert "resume_run_id is not supported" in response.text


def test_phase7_config_and_credentials_posts_are_read_only() -> None:
    client = TestClient(app)

    config_response = client.post("/api/config", json={"llm": {"provider": "openai"}})
    credentials_response = client.post("/api/credentials", json={"OPENAI_API_KEY": "secret"})

    assert config_response.status_code == 405
    assert "read-only" in config_response.text
    assert credentials_response.status_code == 405
    assert "read-only" in credentials_response.text


def test_phase7_runtime_uses_terminating_plan_as_final_route_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.dynamic_os import runtime as runtime_module

    class FakeExecutor:
        def __init__(self, *, event_sink=None, **kwargs) -> None:
            del kwargs
            self._event_sink = event_sink

        async def run(self, *, user_request: str, run_id: str):
            del user_request
            terminate_plan = {
                "run_id": run_id,
                "planning_iteration": 0,
                "horizon": 1,
                "nodes": [
                    {
                        "node_id": "node_stop_1",
                        "role": "writer",
                        "goal": "Stop now",
                        "inputs": [],
                        "allowed_skills": ["draft_report"],
                        "success_criteria": [],
                        "failure_policy": "replan",
                        "expected_outputs": ["ResearchReport"],
                        "needs_review": False,
                    }
                ],
                "edges": [],
                "planner_notes": ["terminate immediately"],
                "terminate": True,
            }
            self._event_sink(
                {
                    "type": "plan_update",
                    "ts": "2026-03-12T00:00:00Z",
                    "run_id": run_id,
                    "planning_iteration": 0,
                    "plan": terminate_plan,
                }
            )
            return SimpleNamespace(termination_reason="planner_terminated")

    monkeypatch.setattr(runtime_module, "Executor", FakeExecutor)
    output_root = Path(".tmp_phase7_runtime_test")
    output_root.mkdir(parents=True, exist_ok=True)
    runtime = runtime_module.DynamicResearchRuntime(root=Path.cwd(), output_root=output_root)

    result = asyncio.run(runtime.run(user_request="stop immediately", run_id="run_phase7_terminate"))

    assert result.status == "completed"
    assert result.route_plan["terminate"] is True
    assert result.route_plan["planner_notes"] == ["terminate immediately"]


def test_phase7_legacy_package_and_scripts_removed() -> None:
    root = Path(__file__).resolve().parents[1]
    assert not (root / "src" / "agent").exists()
    assert not (root / "scripts" / "smoke_test.py").exists()
    assert not (root / "scripts" / "validate_run_outputs.py").exists()
    assert not (root / "scripts" / "fetch_arxiv.py").exists()


def test_phase7_no_legacy_runtime_references_in_live_paths() -> None:
    root = Path(__file__).resolve().parents[1]
    targets = [
        root / "app.py",
        root / "src" / "dynamic_os",
        root / "src" / "server",
        root / "scripts",
        root / "frontend" / "src",
        root / ".github" / "workflows" / "ci.yml",
    ]
    forbidden = ("src.agent", "ResearchOrchestrator", "scripts.smoke_test", "scripts.validate_run_outputs", "6-agent")

    for target in targets:
        paths = [target] if target.is_file() else list(target.rglob("*"))
        for path in paths:
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in forbidden:
                assert token not in text, f"{token} still present in {path}"
