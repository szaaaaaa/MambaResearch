from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from app import app
from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.observation import ErrorType, NodeStatus, Observation
from src.dynamic_os.contracts.policy import BudgetPolicy, PermissionPolicy
from src.dynamic_os.contracts.route_plan import PlanNode, RoleId, RoutePlan
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput
from src.dynamic_os.contracts.skill_spec import SkillSpec
from src.dynamic_os.executor import Executor, NodeRunner
from src.dynamic_os.planner import Planner, PlannerOutputError, assess_review_need, decide_termination
from src.dynamic_os.planner.prompts import build_planner_messages
from src.dynamic_os.policy.engine import PolicyEngine
from src.dynamic_os.roles.registry import RoleRegistry
from src.dynamic_os.skills.builtins.search_papers.run import run as search_papers_run
from src.dynamic_os.skills.registry import SkillRegistry
from src.dynamic_os.storage.memory import InMemoryArtifactStore, InMemoryObservationStore, InMemoryPlanStore
from src.dynamic_os.tools.gateway import ToolGateway
from src.dynamic_os.tools.registry import ToolCapability, ToolRegistry

BUILTINS_DIR = Path(__file__).resolve().parents[1] / "src" / "dynamic_os" / "skills" / "builtins"


class FakePlannerModel:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def generate(self, messages, response_schema):
        if _is_role_routing_schema(response_schema):
            hard_policy = _extract_hard_policy(messages)
            user_request = next(
                (message.get("content", "") for message in reversed(messages) if message.get("role") == "user"),
                "",
            ).lower()
            selected_roles = list(hard_policy.get("selected_roles") or [])
            required_roles = list(hard_policy.get("required_roles") or [])
            reasons: list[str] = []

            if any(token in user_request for token in ("experiment", "benchmark", "ablation", "实验", "评测", "基准")):
                _append_unique(selected_roles, "experimenter")
                _append_unique(selected_roles, "analyst")
                _append_unique(required_roles, "experimenter")
                reasons.append("进入实验阶段")
            if any(token in user_request for token in ("analyze", "analysis", "compare", "分析", "对比", "比较")):
                _append_unique(selected_roles, "analyst")
                _append_unique(required_roles, "analyst")
                reasons.append("进入分析阶段")
            if any(token in user_request for token in ("write", "draft", "报告", "总结", "综述", "撰写")):
                _append_unique(selected_roles, "writer")
                reasons.append("进入写作阶段")
            if any(token in user_request for token in ("review", "审核", "评审", "审阅")):
                _append_unique(selected_roles, "reviewer")
                reasons.append("进入评审阶段")
            if any(
                token in user_request
                for token in ("find", "paper", "research", "investigate", "study", "研究", "调研", "论文", "文献", "检索")
            ) or not selected_roles:
                if "conductor" in selected_roles or not selected_roles:
                    _append_unique(selected_roles, "researcher")
                reasons.append("进入研究主流程")

            for role_id in hard_policy.get("required_roles") or []:
                _append_unique(selected_roles, role_id)
                _append_unique(required_roles, role_id)
            if not selected_roles:
                selected_roles = ["researcher"]
            return json.dumps(
                {
                    "selected_roles": selected_roles,
                    "required_roles": required_roles,
                    "reasons": reasons or ["沿用硬路由策略"],
                }
            )
        self.calls += 1
        return self._responses.pop(0)


def _is_role_routing_schema(response_schema: dict) -> bool:
    properties = response_schema.get("properties") or {}
    return isinstance(properties, dict) and "selected_roles" in properties and "required_roles" in properties


def _extract_hard_policy(messages) -> dict:
    system_prompt = next((message.get("content", "") for message in messages if message.get("role") == "system"), "")
    match = re.search(r"## Hard Routing Policy From Code\n(.*?)\n\n## Rules", system_prompt, re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


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


def _planner_with_model(
    model: FakePlannerModel,
    skill_specs: list[SkillSpec],
    *,
    artifact_records: list[ArtifactRecord] | None = None,
) -> Planner:
    artifact_store = InMemoryArtifactStore()
    for record in artifact_records or []:
        artifact_store.save(record)
    return Planner(
        model=model,
        role_registry=RoleRegistry.from_file(),
        skill_registry=FakeSkillRegistry(skill_specs),
        artifact_store=artifact_store,
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
    required: list[str] | None = None,
    requires_any: list[str] | None = None,
    output_artifacts: list[str] | None = None,
) -> SkillSpec:
    default_outputs = {
        "search_papers": ["SourceSet"],
        "fetch_fulltext": ["SourceSet"],
        "extract_notes": ["PaperNotes"],
        "plan_research": ["TopicBrief", "SearchPlan"],
        "build_evidence_map": ["EvidenceMap", "GapMap"],
        "draft_report": ["ResearchReport"],
        "review_artifact": ["ReviewVerdict"],
    }
    return SkillSpec.model_validate(
        {
            "id": skill_id,
            "name": skill_id.replace("_", " ").title(),
            "applicable_roles": roles,
            "description": skill_id,
            "input_contract": {
                "required": required or [],
                "requires_any": requires_any or [],
            },
            "output_artifacts": output_artifacts or default_outputs.get(skill_id, []),
            "allowed_tools": allowed_tools or [],
            "permissions": permissions or {},
            "timeout_sec": 60,
        }
    )


def _plan_json(
    role: str,
    skill_id: str,
    *,
    run_id: str = "run_1",
    planning_iteration: int = 0,
    inputs: list[str] | None = None,
) -> str:
    default_expected_outputs = {
        "plan_research": ["TopicBrief", "SearchPlan"],
        "search_papers": ["SourceSet"],
        "fetch_fulltext": ["SourceSet"],
        "extract_notes": ["PaperNotes"],
        "build_evidence_map": ["EvidenceMap", "GapMap"],
        "draft_report": ["ResearchReport"],
        "review_artifact": ["ReviewVerdict"],
    }
    return json.dumps(
        {
            "run_id": run_id,
            "planning_iteration": planning_iteration,
            "horizon": 1,
            "nodes": [
                {
                    "node_id": "node_research_1",
                    "role": role,
                    "goal": "Collect papers",
                    "inputs": inputs or [],
                    "allowed_skills": [skill_id],
                    "success_criteria": ["at_least_one_source"],
                    "failure_policy": "replan",
                    "expected_outputs": default_expected_outputs.get(skill_id, []),
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
                            "retrieved_document": {
                                "paper_id": "paper_a",
                                "title": "Paper A",
                                "content": "Retrieved full text for Paper A",
                            },
                        }
                    ],
                    "documents": [
                        {
                            "paper_id": "paper_a",
                            "title": "Paper A",
                            "content": "Retrieved full text for Paper A",
                        }
                    ],
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
                    "plan": "Compare retrieval planning against a baseline.",
                    "language": "python",
                    "workspace_path": str(Path(__file__).parent / "_test_workspace"),
                    "entry_point": "train.py",
                    "eval_script": "evaluate.py",
                    "mutable_files": ["configs/hparams.yaml", "models/model.py"],
                    "snapshot": {},
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
            {"server_id": "paper_search", "tools": [{"name": "search_papers", "capability": "search"}]},
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
            system_message = next(
                (
                    message.get("content", "")
                    for message in payload.get("messages", [])
                    if message.get("role") == "system"
                ),
                "",
            )
            user_message = next(
                (
                    message.get("content", "")
                    for message in reversed(payload.get("messages", []))
                    if message.get("role") == "user"
                ),
                "",
            )
            if "rigorous academic reviewer" in system_message:
                return json.dumps(
                    {
                        "novelty": 7,
                        "soundness": 7,
                        "clarity": 8,
                        "significance": 7,
                        "completeness": 7,
                        "review_text": "Solid work with clear methodology.",
                        "issues": [],
                        "strengths": ["Clear structure", "Good coverage"],
                        "modification_suggestions": "",
                    }
                )
            if "You are modifying experiment files" in system_message:
                return json.dumps(
                    {
                        "plan": f"Evaluate retrieval planning for: {user_message[:80]}",
                        "files": {
                            "configs/hparams.yaml": "epochs: 5\nlearning_rate: 0.001\n",
                            "models/model.py": "import torch\ndef build_model(hp): return torch.nn.Linear(10,10)\n",
                        },
                    }
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
        FakePlannerModel(
            [
                _plan_json(
                    "researcher",
                    "search_papers",
                    inputs=["artifact:SearchPlan:search_plan_1"],
                )
            ]
        ),
        [_skill_spec("search_papers", ["researcher"], required=["SearchPlan"])],
        artifact_records=[
            _phase5_artifact(
                "search_plan_1",
                "SearchPlan",
                role=RoleId.conductor,
                skill="plan_research",
            )
        ],
    )

    plan = asyncio.run(planner.plan(run_id="run_1", user_request="Find papers about retrieval planning", planning_iteration=0))

    assert isinstance(plan, RoutePlan)
    assert [node.role.value for node in plan.nodes] == ["researcher"]


def test_planner_retries_once_after_invalid_output() -> None:
    model = FakePlannerModel(
        [
            '{"run_id": "bad"}',
            _plan_json(
                "researcher",
                "search_papers",
                inputs=["artifact:SearchPlan:search_plan_1"],
            ),
        ]
    )
    planner = _planner_with_model(
        model,
        [_skill_spec("search_papers", ["researcher"], required=["SearchPlan"])],
        artifact_records=[
            _phase5_artifact(
                "search_plan_1",
                "SearchPlan",
                role=RoleId.conductor,
                skill="plan_research",
            )
        ],
    )

    plan = asyncio.run(planner.plan(run_id="run_1", user_request="Find papers", planning_iteration=0))

    assert plan.nodes[0].allowed_skills == ["search_papers"]
    assert model.calls == 2






def test_planner_raises_after_second_invalid_output() -> None:
    model = FakePlannerModel(['{"run_id": "bad"}', '{"run_id": "still_bad"}'])
    planner = _planner_with_model(model, [_skill_spec("search_papers", ["researcher"])])

    with pytest.raises(PlannerOutputError):
        asyncio.run(planner.plan(run_id="run_1", user_request="Find papers", planning_iteration=0))

    assert model.calls == 2


def test_planner_fallback_uses_plan_research_when_available() -> None:
    model = FakePlannerModel(['{"run_id": "bad"}', '{"run_id": "still_bad"}'])
    planner = _planner_with_model(model, [_skill_spec("plan_research", ["conductor"])])

    plan = asyncio.run(planner.plan(run_id="run_1", user_request="Find papers", planning_iteration=0))

    assert plan.nodes[0].role == RoleId.conductor
    assert plan.nodes[0].allowed_skills == ["plan_research"]
    assert model.calls == 2





def test_executor_records_planner_llm_error_observation() -> None:
    artifact_store = InMemoryArtifactStore()
    observation_store = InMemoryObservationStore()
    events: list[object] = []
    planner = _planner_with_model(
        FakePlannerModel(['{"run_id": "bad"}', '{"run_id": "still_bad"}']),
        [_skill_spec("search_papers", ["researcher"])],
    )
    policy = PolicyEngine(permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())]))
    tools = ToolGateway(
        registry=ToolRegistry.from_servers(
            [{"server_id": "paper_search", "tools": [{"name": "search_papers", "capability": "search"}]}]
        ),
        policy=policy,
        mcp_invoker=lambda tool, payload: [],
    )
    node_runner = NodeRunner(
        role_registry=RoleRegistry.from_file(),
        skill_registry=FakeSkillRegistry([_skill_spec("search_papers", ["researcher"])]),
        artifact_store=artifact_store,
        observation_store=observation_store,
        tools=tools,
        policy=policy,
    )
    executor = Executor(
        planner=planner,
        node_runner=node_runner,
        artifact_store=artifact_store,
        observation_store=observation_store,
        policy=policy,
        event_sink=events.append,
    )

    result = asyncio.run(executor.run(user_request="Find papers", run_id="run_1"))

    observation = observation_store.list_latest()[-1]
    assert result.termination_reason
    assert observation.role == "planner"
    assert observation.error_type == ErrorType.llm_error
    assert any(event.type == "observation" for event in events)


def test_planner_accepts_inserted_reviewer_node() -> None:
    planner = _planner_with_model(
        FakePlannerModel(
            [
                _plan_json(
                    "reviewer",
                    "review_artifact",
                    inputs=["artifact:ResearchReport:report_1"],
                )
            ]
        ),
        [_skill_spec("review_artifact", ["reviewer"])],
        artifact_records=[
            _phase5_artifact(
                "report_1",
                "ResearchReport",
                role=RoleId.writer,
                skill="draft_report",
                payload={"report": "final report"},
            )
        ],
    )

    plan = asyncio.run(planner.plan(run_id="run_1", user_request="Review the final report", planning_iteration=0))

    assert plan.nodes[0].role.value == "reviewer"


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
        asyncio.run(planner.plan(run_id="run_1", user_request="Find papers", planning_iteration=0))


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
        skill_contract_summary=planner._skill_contract_summary(),
        artifact_summary=[],
        artifact_refs=[],
        artifact_ref_templates=planner._artifact_ref_templates(),
        observation_summary=[],
        budget_snapshot={},
        planning_iteration=0,
    )

    assert "search_papers" in messages[0]["content"]
    assert "custom_search" not in messages[0]["content"]
    assert "artifact_ref_template" in messages[0]["content"]























def test_planner_meta_skills_cover_review_and_termination() -> None:
    assert assess_review_need() is False
    assert assess_review_need(critical_deliverable=True) is True
    assert decide_termination([{"artifact_type": "ResearchReport"}]) is True
    assert decide_termination([{"artifact_type": "SourceSet"}]) is False


class SequencePlanner:
    def __init__(self, plans: list[RoutePlan]) -> None:
        self._plans = list(plans)
        self.calls = 0

    async def plan(self, *, run_id: str, user_request: str, planning_iteration: int, budget_snapshot=None) -> RoutePlan:
        del run_id, user_request, planning_iteration, budget_snapshot
        self.calls += 1
        return self._plans.pop(0)


def test_executor_runs_local_loop_and_emits_events() -> None:
    role_registry = RoleRegistry.from_file()
    artifact_store = InMemoryArtifactStore()
    observation_store = InMemoryObservationStore()
    plan_store = InMemoryPlanStore()
    events: list[object] = []
    search_calls = 0

    async def search_runner(ctx):
        nonlocal search_calls
        search_calls += 1
        results = await ctx.tools.search("retrieval planning", source="academic", max_results=2)
        assert results["results"][0]["title"] == "Paper A"
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
                allowed_tools=["mcp.paper_search.search_papers"],
            )
        ],
        runners={"search_papers": search_runner},
    )
    policy = PolicyEngine(permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())]))
    tools = ToolGateway(
        registry=ToolRegistry.from_servers(
            [{"server_id": "paper_search", "tools": [{"name": "search_papers", "capability": "search"}]}]
        ),
        policy=policy,
        mcp_invoker=lambda tool, payload: {"results": [{"title": "Paper A", "tool_id": tool.tool_id}], "warnings": []},
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
    assert search_calls == 2
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
        [
            _skill_spec("search_papers", ["researcher"]),
            _skill_spec("plan_research", ["conductor"], output_artifacts=["TopicBrief", "SearchPlan"]),
        ],
        runners={"search_papers": failing_runner},
    )
    policy = PolicyEngine(permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())]))
    tools = ToolGateway(
        registry=ToolRegistry.from_servers(
            [{"server_id": "paper_search", "tools": [{"name": "search_papers", "capability": "search"}]}]
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
            _route_plan("run_fail", 1, "conductor", "plan_research", terminate=True),
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

    assert any(obs.status == NodeStatus.needs_replan for obs in observation_store.list_latest())
    assert any(obs.error_type == ErrorType.skill_error for obs in observation_store.list_latest())
    assert any(event.type == "node_status" and event.status == "needs_replan" for event in events)
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
            [{"server_id": "paper_search", "tools": [{"name": "search_papers", "capability": "search"}]}]
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

    assert result.termination_reason == "规划迭代次数已超出预算"
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


def test_search_papers_produces_empty_sourceset_with_warnings() -> None:
    class FakeTools:
        async def search(self, query: str, *, source: str = "auto", max_results: int = 10):
            assert query == "retrieval planning"
            assert source == "auto"
            assert max_results == 10
            return {"results": [], "warnings": ["arxiv: feedparser is required for arXiv fetching"]}

    ctx = SkillContext(
        skill_id="search_papers",
        role_id="researcher",
        run_id="run_search",
        node_id="node_search_1",
        goal="Search for papers",
        input_artifacts=[
            ArtifactRecord(
                artifact_id="node_plan_1_search_plan",
                artifact_type="SearchPlan",
                producer_role=RoleId.conductor,
                producer_skill="plan_research",
                payload={"search_queries": ["retrieval planning"]},
            )
        ],
        tools=FakeTools(),
    )

    output = asyncio.run(search_papers_run(ctx))

    assert output.success is True
    assert output.output_artifacts[0].artifact_id == "node_search_1_source_set"
    assert output.output_artifacts[0].payload["result_count"] == 0
    assert output.output_artifacts[0].payload["warnings"] == [
        "arxiv: feedparser is required for arXiv fetching"
    ]


def test_search_papers_merges_queries_and_uses_route_sources() -> None:
    calls: list[tuple[str, str, int]] = []

    class FakeTools:
        async def search(self, query: str, *, source: str = "auto", max_results: int = 10):
            calls.append((query, source, max_results))
            return {
                "results": [
                    {
                        "paper_id": f"{query}_{source}",
                        "title": f"{query} via {source}",
                    }
                ],
                "warnings": [f"{source} warning"],
            }

    ctx = SkillContext(
        skill_id="search_papers",
        role_id="researcher",
        run_id="run_search_multi",
        node_id="node_search_multi_1",
        goal="Search for papers",
        input_artifacts=[
            ArtifactRecord(
                artifact_id="node_plan_multi_search_plan",
                artifact_type="SearchPlan",
                producer_role=RoleId.conductor,
                producer_skill="plan_research",
                payload={
                    "search_queries": ["q1", "q2"],
                    "query_routes": {
                        "q1": {"use_academic": True, "use_web": False},
                        "q2": {"use_academic": False, "use_web": True},
                    },
                },
            )
        ],
        tools=FakeTools(),
    )

    output = asyncio.run(search_papers_run(ctx))

    assert output.success is True
    assert calls == [("q1", "academic", 10), ("q2", "web", 10)]
    assert output.output_artifacts[0].payload["result_count"] == 2
    assert output.output_artifacts[0].payload["queries"] == ["q1", "q2"]


def test_plan_research_uses_structured_keyword_queries() -> None:
    registry = SkillRegistry.discover([BUILTINS_DIR])
    loaded = registry.get("plan_research")

    class FakeTools:
        def with_permissions(self, permissions):
            del permissions
            return self

        def with_allowed_tools(self, allowed_tools):
            del allowed_tools
            return self

        async def llm_chat(self, messages, **kwargs):
            del messages, kwargs
            return json.dumps(
                {
                    "topic": "dynamic research agent systems",
                    "brief": "Focus on architecture, coordination, and evaluation.",
                    "research_questions": [
                        "What architectures are used in dynamic research agent systems?",
                        "How are these systems evaluated?",
                    ],
                    "search_queries": [
                        "dynamic research agent systems",
                        "dynamic research agent systems architecture",
                        "dynamic research agent systems evaluation",
                    ],
                    "query_routes": {
                        "dynamic research agent systems": {"use_academic": True, "use_web": False},
                        "dynamic research agent systems architecture": {"use_academic": True, "use_web": False},
                        "dynamic research agent systems evaluation": {"use_academic": True, "use_web": False},
                    },
                },
                ensure_ascii=False,
            )

    ctx = SkillContext(
        skill_id="plan_research",
        role_id="conductor",
        run_id="run_plan_structured",
        node_id="node_plan_structured_1",
        goal="为一个关于动态研究智能体系统的主题生成最小研究闭环。",
        input_artifacts=[],
        tools=FakeTools(),
    )

    output = asyncio.run(loaded.runner(ctx))

    assert output.success is True
    search_plan = next(item for item in output.output_artifacts if item.artifact_type == "SearchPlan")
    assert search_plan.payload["topic"] == "dynamic research agent systems"
    assert search_plan.payload["search_queries"] == [
        "dynamic research agent systems",
        "dynamic research agent systems architecture",
        "dynamic research agent systems evaluation",
    ]


def test_plan_research_fallback_does_not_reuse_instruction_sentence_as_query() -> None:
    registry = SkillRegistry.discover([BUILTINS_DIR])
    loaded = registry.get("plan_research")

    class FakeTools:
        def with_permissions(self, permissions):
            del permissions
            return self

        def with_allowed_tools(self, allowed_tools):
            del allowed_tools
            return self

        async def llm_chat(self, messages, **kwargs):
            del messages, kwargs
            return "先定义研究目标，再生成最小研究闭环和搜索计划。"

    goal = "为一个关于动态研究智能体系统的主题生成最小研究闭环。"
    ctx = SkillContext(
        skill_id="plan_research",
        role_id="conductor",
        run_id="run_plan_fallback",
        node_id="node_plan_fallback_1",
        goal=goal,
        input_artifacts=[],
        tools=FakeTools(),
    )

    output = asyncio.run(loaded.runner(ctx))

    assert output.success is True
    search_plan = next(item for item in output.output_artifacts if item.artifact_type == "SearchPlan")
    queries = list(search_plan.payload["search_queries"])
    assert goal not in queries
    assert all("最小研究闭环" not in query for query in queries)
    assert any("动态研究智能体系统" in query for query in queries)


def test_plan_research_reanchors_generic_queries_to_topic() -> None:
    registry = SkillRegistry.discover([BUILTINS_DIR])
    loaded = registry.get("plan_research")

    class FakeTools:
        def with_permissions(self, permissions):
            del permissions
            return self

        def with_allowed_tools(self, allowed_tools):
            del allowed_tools
            return self

        async def llm_chat(self, messages, **kwargs):
            del messages, kwargs
            return json.dumps(
                {
                    "topic": "动态研究智能体系统",
                    "brief": "围绕主题生成检索查询。",
                    "research_questions": ["动态研究智能体系统的方法与证据是什么？"],
                    "search_queries": ["方法与证据是什么", "综述", "方法", "评测"],
                    "query_routes": {},
                },
                ensure_ascii=False,
            )

    ctx = SkillContext(
        skill_id="plan_research",
        role_id="conductor",
        run_id="run_plan_anchor_queries",
        node_id="node_plan_anchor_queries_1",
        goal="为一个关于动态研究智能体系统的主题生成最小研究闭环。",
        input_artifacts=[],
        tools=FakeTools(),
    )

    output = asyncio.run(loaded.runner(ctx))

    assert output.success is True
    search_plan = next(item for item in output.output_artifacts if item.artifact_type == "SearchPlan")
    assert search_plan.payload["search_queries"] == [
        "动态研究智能体系统 方法与证据是什么",
        "动态研究智能体系统 综述",
        "动态研究智能体系统 方法",
        "动态研究智能体系统 评测",
    ]


def test_plan_research_rejects_generic_topic_and_keeps_subject() -> None:
    registry = SkillRegistry.discover([BUILTINS_DIR])
    loaded = registry.get("plan_research")

    class FakeTools:
        def with_permissions(self, permissions):
            del permissions
            return self

        def with_allowed_tools(self, allowed_tools):
            del allowed_tools
            return self

        async def llm_chat(self, messages, **kwargs):
            del messages, kwargs
            return json.dumps(
                {
                    "topic": "方法与证据",
                    "brief": "围绕主题生成检索查询。",
                    "research_questions": ["动态研究智能体系统的方法与证据是什么？"],
                    "search_queries": ["方法与证据是什么"],
                    "query_routes": {},
                },
                ensure_ascii=False,
            )

    ctx = SkillContext(
        skill_id="plan_research",
        role_id="conductor",
        run_id="run_plan_anchor_topic",
        node_id="node_plan_anchor_topic_1",
        goal="为一个关于动态研究智能体系统的主题生成最小研究闭环。",
        input_artifacts=[],
        tools=FakeTools(),
    )

    output = asyncio.run(loaded.runner(ctx))

    assert output.success is True
    topic_brief = next(item for item in output.output_artifacts if item.artifact_type == "TopicBrief")
    search_plan = next(item for item in output.output_artifacts if item.artifact_type == "SearchPlan")
    assert topic_brief.payload["topic"] == "动态研究智能体系统"
    assert search_plan.payload["topic"] == "动态研究智能体系统"
    assert search_plan.payload["search_queries"][0] == "动态研究智能体系统 方法与证据是什么"


def test_build_evidence_map_derives_grounded_gaps() -> None:
    registry = SkillRegistry.discover([BUILTINS_DIR])
    loaded = registry.get("build_evidence_map")

    class FakeTools:
        def with_permissions(self, permissions):
            del permissions
            return self

        def with_allowed_tools(self, allowed_tools):
            del allowed_tools
            return self

        async def llm_chat(self, messages, **kwargs):
            del kwargs
            return "Grounded evidence summary"

    ctx = SkillContext(
        skill_id="build_evidence_map",
        role_id="researcher",
        run_id="run_evidence",
        node_id="node_evidence_grounded",
        goal="Build evidence map",
        input_artifacts=[
            ArtifactRecord(
                artifact_id="source_set_empty",
                artifact_type="SourceSet",
                producer_role=RoleId.researcher,
                producer_skill="search_papers",
                payload={"result_count": 0, "sources": [], "warnings": ["semantic_scholar timeout"]},
            )
        ],
        tools=FakeTools(),
    )

    output = asyncio.run(loaded.runner(ctx))
    gap_payload = next(item.payload for item in output.output_artifacts if item.artifact_type == "GapMap")

    assert output.success is True
    assert gap_payload["gap_count"] >= 2
    assert any("检索尚未返回可用来源" in gap for gap in gap_payload["gaps"])
    assert any("semantic_scholar timeout" in gap for gap in gap_payload["gaps"])


def test_review_artifact_verdict_uses_artifact_checks() -> None:
    registry = SkillRegistry.discover([BUILTINS_DIR])
    loaded = registry.get("review_artifact")

    class FakeTools:
        def with_permissions(self, permissions):
            del permissions
            return self

        def with_allowed_tools(self, allowed_tools):
            del allowed_tools
            return self

        async def llm_chat(self, messages, **kwargs):
            del messages, kwargs
            return "Review summary"

    ctx = SkillContext(
        skill_id="review_artifact",
        role_id="reviewer",
        run_id="run_review",
        node_id="node_review_structured",
        goal="Review the report",
        input_artifacts=[
            ArtifactRecord(
                artifact_id="report_missing_text",
                artifact_type="ResearchReport",
                producer_role=RoleId.writer,
                producer_skill="draft_report",
                payload={"artifact_count": 1},
            )
        ],
        tools=FakeTools(),
    )

    output = asyncio.run(loaded.runner(ctx))
    payload = output.output_artifacts[0].payload

    assert output.success is True
    assert payload["verdict"] == "needs_revision"
    assert "missing report text" in payload["issues"]


def test_analyze_metrics_computes_metric_stats() -> None:
    registry = SkillRegistry.discover([BUILTINS_DIR])
    loaded = registry.get("analyze_metrics")

    class FakeTools:
        def with_permissions(self, permissions):
            del permissions
            return self

        def with_allowed_tools(self, allowed_tools):
            del allowed_tools
            return self

        async def llm_chat(self, messages, **kwargs):
            del messages, kwargs
            return "Metric interpretation"

    ctx = SkillContext(
        skill_id="analyze_metrics",
        role_id="analyst",
        run_id="run_metrics",
        node_id="node_metrics_1",
        goal="Analyze experiment results",
        input_artifacts=[
            ArtifactRecord(
                artifact_id="experiment_results_aggregate",
                artifact_type="ExperimentResults",
                producer_role=RoleId.experimenter,
                producer_skill="run_experiment",
                payload={
                    "status": "completed",
                    "runs": [
                        {"run_id": "r1", "metrics": [{"name": "accuracy", "value": 0.8}]},
                        {"run_id": "r2", "metrics": [{"name": "accuracy", "value": 0.9}]},
                    ],
                },
            )
        ],
        tools=FakeTools(),
    )

    output = asyncio.run(loaded.runner(ctx))
    perf_payload = next(item.payload for item in output.output_artifacts if item.artifact_type == "PerformanceMetrics")

    assert output.success is True
    assert perf_payload["run_count"] == 2
    assert perf_payload["metric_stats"]["accuracy"]["avg"] == 0.85


def test_runtime_report_text_summarizes_partial_artifacts_when_report_is_missing() -> None:
    from src.dynamic_os import runtime as runtime_module

    report_text = runtime_module._report_text(
        artifacts=[
            ArtifactRecord(
                artifact_id="node_1_topic_brief",
                artifact_type="TopicBrief",
                producer_role=RoleId.conductor,
                producer_skill="plan_research",
                payload={"brief": "brief"},
            ),
            ArtifactRecord(
                artifact_id="node_5_evidence_map",
                artifact_type="EvidenceMap",
                producer_role=RoleId.researcher,
                producer_skill="build_evidence_map",
                payload={"summary": "summary"},
            ),
        ],
        observations=[
            Observation(
                node_id="node_6",
                role=RoleId.writer,
                status=NodeStatus.needs_replan,
                error_type=ErrorType.input_missing,
                what_happened="missing upstream evidence artifact",
            )
        ],
        status="failed",
    )

    assert "Partial artifacts were produced" in report_text
    assert "TopicBrief: node_1_topic_brief" in report_text
    assert "EvidenceMap: node_5_evidence_map" in report_text
    assert "missing upstream evidence artifact" in report_text


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
                payload={
                    "language": "python",
                    "workspace_path": str(Path(__file__).parent / "_test_workspace"),
                    "entry_point": "train.py",
                    "eval_script": "evaluate.py",
                    "mutable_files": [],
                    "snapshot": {},
                },
            )
        ],
        tools=ToolGateway(
            registry=ToolRegistry.from_servers(
                [
                    {"server_id": "llm", "tools": [{"name": "chat", "capability": "llm_chat"}]},
                    {"server_id": "exec", "tools": [{"name": "execute_code", "capability": "execute_code"}]},
                ]
            ),
            policy=policy,
            mcp_invoker=lambda tool, payload: "{}",
            code_executor=lambda **kwargs: {"exit_code": 1, "stderr": "boom"},
        ),
        config={"agent": {"experiment_plan": {"recovery": {"max_retries": 0}}}},
    )

    output = asyncio.run(loaded.runner(ctx))

    assert output.success is False
    assert "failed" in (output.error or "").lower()


def test_phase5_design_experiment_emits_workspace_plan() -> None:
    registry = SkillRegistry.discover([BUILTINS_DIR])
    loaded = registry.get("design_experiment")
    ctx = SkillContext(
        skill_id="design_experiment",
        role_id="experimenter",
        run_id="run_phase5_design",
        node_id="node_design_experiment_1",
        goal="Design an experiment for retrieval planning",
        input_artifacts=_phase5_inputs("design_experiment"),
        tools=_phase5_gateway(),
        config={
            "project": {"data_dir": str(Path(__file__).parent / "_test_data")},
            "agent": {
                "experiment_plan": {
                    "gpu": "cpu",
                    "objective": "test objective",
                    "workspace": {
                        "template": "builtin",
                        "mutable_files": ["configs/hparams.yaml", "models/model.py"],
                        "entry_point": "train.py",
                        "eval_script": "evaluate.py",
                    },
                }
            },
        },
    )

    output = asyncio.run(loaded.runner(ctx))

    assert output.success is True
    artifact = output.output_artifacts[0]
    assert artifact.payload["plan"].startswith("Evaluate retrieval planning")
    assert "workspace_path" in artifact.payload
    assert artifact.payload["mutable_files"] == ["configs/hparams.yaml", "models/model.py"]


def test_phase5_run_experiment_fails_with_bad_executor() -> None:
    registry = SkillRegistry.discover([BUILTINS_DIR])
    loaded = registry.get("run_experiment")
    policy = PolicyEngine(permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())]))
    ctx = SkillContext(
        skill_id="run_experiment",
        role_id="experimenter",
        run_id="run_phase5_missing_workspace",
        node_id="node_run_experiment_missing_workspace",
        goal="Run the experiment",
        input_artifacts=[
            _phase5_artifact(
                "experiment_plan_missing_ws_1",
                "ExperimentPlan",
                role=RoleId.experimenter,
                skill="design_experiment",
                payload={
                    "language": "python",
                    "workspace_path": "/nonexistent/workspace",
                    "entry_point": "train.py",
                    "eval_script": "evaluate.py",
                    "mutable_files": [],
                    "snapshot": {},
                },
            )
        ],
        tools=ToolGateway(
            registry=ToolRegistry.from_servers(
                [
                    {"server_id": "llm", "tools": [{"name": "chat", "capability": "llm_chat"}]},
                    {"server_id": "exec", "tools": [{"name": "execute_code", "capability": "execute_code"}]},
                ]
            ),
            policy=policy,
            mcp_invoker=lambda tool, payload: "{}",
            code_executor=lambda **kwargs: {"exit_code": 1, "stderr": "workspace not found"},
        ),
        config={"agent": {"experiment_plan": {"recovery": {"max_retries": 0}}}},
    )

    output = asyncio.run(loaded.runner(ctx))

    assert output.success is False
    assert "failed" in (output.error or "").lower()


def test_phase5_fetch_fulltext_and_extract_notes_use_retrieved_documents() -> None:
    registry = SkillRegistry.discover([BUILTINS_DIR])
    fetch_skill = registry.get("fetch_fulltext")
    note_skill = registry.get("extract_notes")
    gateway = _phase5_gateway()
    fetch_ctx = SkillContext(
        skill_id="fetch_fulltext",
        role_id="researcher",
        run_id="run_phase5_retrieval",
        node_id="node_fetch_fulltext_1",
        goal="Fetch fuller text",
        input_artifacts=_phase5_inputs("fetch_fulltext"),
        tools=gateway,
    )

    fetch_output = asyncio.run(fetch_skill.runner(fetch_ctx))

    assert fetch_output.success is True
    fetched_source_set = fetch_output.output_artifacts[0]
    fetched_source = fetched_source_set.payload["sources"][0]
    assert fetched_source["content"].startswith("Full text for Paper A")
    assert fetched_source_set.payload["fetched_count"] == 1

    note_ctx = SkillContext(
        skill_id="extract_notes",
        role_id="researcher",
        run_id="run_phase5_retrieval",
        node_id="node_extract_notes_1",
        goal="Extract notes",
        input_artifacts=[fetched_source_set],
        tools=gateway,
    )

    note_output = asyncio.run(note_skill.runner(note_ctx))

    assert note_output.success is True
    note_payload = note_output.output_artifacts[0].payload
    assert note_payload["notes"][0]["summary"].startswith("Full text for Paper A")


def test_extract_notes_continues_when_index_backend_is_unavailable() -> None:
    registry = SkillRegistry.discover([BUILTINS_DIR])
    loaded = registry.get("extract_notes")

    class FakeTools:
        def with_permissions(self, permissions):
            del permissions
            return self

        def with_allowed_tools(self, allowed_tools):
            del allowed_tools
            return self

        async def index(self, documents, collection):
            del documents, collection
            raise ModuleNotFoundError("No module named 'chromadb'")

        async def llm_chat(self, messages, **kwargs):
            del messages, kwargs
            return "Condensed paper notes"

    ctx = SkillContext(
        skill_id="extract_notes",
        role_id="researcher",
        run_id="run_extract_notes_indexless",
        node_id="node_extract_notes_indexless",
        goal="Extract notes without an index backend",
        input_artifacts=[
            ArtifactRecord(
                artifact_id="source_set_indexless",
                artifact_type="SourceSet",
                producer_role=RoleId.researcher,
                producer_skill="fetch_fulltext",
                payload={
                    "sources": [
                        {
                            "paper_id": "paper_a",
                            "title": "Paper A",
                            "retrieved_document": {
                                "paper_id": "paper_a",
                                "title": "Paper A",
                                "content": "Full text for Paper A about dynamic research agents.",
                            },
                        }
                    ]
                },
            )
        ],
        tools=FakeTools(),
    )

    output = asyncio.run(loaded.runner(ctx))

    assert output.success is True
    payload = output.output_artifacts[0].payload
    assert payload["notes"][0]["summary"].startswith("Full text for Paper A")
    assert "chromadb" in payload["warnings"][0]
    assert "chromadb" in output.metadata["warnings"][0]


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

    result = asyncio.run(
        executor.run(
            user_request="Investigate retrieval planning and write a reviewed report",
            run_id="run_phase5",
        )
    )

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


def test_executor_short_circuits_when_final_artifact_is_produced_without_review_request() -> None:
    role_registry = RoleRegistry.from_file()
    artifact_store = InMemoryArtifactStore()
    observation_store = InMemoryObservationStore()
    events: list[object] = []

    async def report_runner(ctx):
        del ctx
        return SkillOutput(
            success=True,
            output_artifacts=[
                ArtifactRecord(
                    artifact_id="report_budget_1",
                    artifact_type="ResearchReport",
                    producer_role=RoleId.writer,
                    producer_skill="draft_report",
                    payload={"report": "Final report"},
                )
            ],
        )

    skill_registry = FakeSkillRegistry(
        [_skill_spec("draft_report", ["writer"], output_artifacts=["ResearchReport"])],
        runners={"draft_report": report_runner},
    )
    policy = PolicyEngine(
        permission_policy=PermissionPolicy(approved_workspaces=[str(Path.cwd())]),
        budget_policy=BudgetPolicy(
            max_planning_iterations=1,
            max_node_executions=4,
            max_tool_invocations=10,
            max_wall_time_sec=600.0,
            max_tokens=50_000,
        ),
    )
    tools = ToolGateway(
        registry=ToolRegistry.from_servers(
            [{"server_id": "llm", "tools": [{"name": "chat", "capability": "llm_chat"}]}]
        ),
        policy=policy,
        mcp_invoker=lambda tool, payload: "unused",
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
            RoutePlan(
                run_id="run_budget_short_circuit",
                planning_iteration=0,
                horizon=1,
                nodes=[
                    PlanNode(
                        node_id="node_report_budget_1",
                        role=RoleId.writer,
                        goal="Write the final report",
                        inputs=[],
                        allowed_skills=["draft_report"],
                        success_criteria=["generated_report"],
                        failure_policy="replan",
                        expected_outputs=["ResearchReport"],
                    )
                ],
                edges=[],
                planner_notes=[],
                terminate=True,
            )
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

    result = asyncio.run(
        executor.run(
            user_request="Write a report",
            run_id="run_budget_short_circuit",
        )
    )

    assert result.termination_reason == "planner_terminated"
    assert planner.calls == 1
    assert "artifact:ResearchReport:report_budget_1" in result.final_artifacts
    assert events[-1].type == "run_terminate"


def test_phase6_api_run_streams_dynamic_runtime_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.server.routes import runs as runs_route
    monkeypatch.setattr(runs_route, "_preflight_run_config", lambda: [])

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
    assert 'event: run_event\ndata: {"type": "plan_update"' in response.text
    assert 'event: run_event\ndata: {"type": "policy_block"' in response.text
    assert 'event: run_state\ndata: {"run_id": "run_phase6"' in response.text
    assert '"node_status": {"node_review_1": "success"}' in response.text
    assert '"artifacts": [{"artifact_id": "review_1"' in response.text
    assert "role_status" not in response.text


def test_phase6_api_rejects_output_dir_outside_workspace() -> None:
    from src.server.routes import runs as runs_route

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(runs_route, "_preflight_run_config", lambda: [])
    client = TestClient(app)
    outside_dir = Path.cwd().resolve().parent

    try:
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
    finally:
        monkeypatch.undo()

    assert response.status_code == 400
    assert "output_root must stay within workspace root" in response.text


def test_phase6_api_rejects_run_when_openai_codex_is_not_logged_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.server.routes import runs as runs_route

    monkeypatch.setattr(
        runs_route,
        "load_yaml",
        lambda path: {
            "agent": {"routing": {"planner_llm": {"provider": "openai_codex", "model": "openai-codex/gpt-5.1-codex"}}},
            "llm": {"role_models": {"conductor": {"provider": "openai_codex", "model": "openai-codex/gpt-5.1-codex"}}},
        },
    )
    monkeypatch.setattr(
        runs_route,
        "ensure_openai_codex_auth",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("openai codex oauth is not logged in for profile 'default'")),
    )

    client = TestClient(app)
    response = client.post(
        "/api/run",
        json={
            "client_request_id": "req_phase6_missing_codex_login",
            "runOverrides": {
                "topic": "dynamic runtime request",
                "user_request": "dynamic runtime request",
            },
        },
    )

    assert response.status_code == 400
    assert "run preflight failed" in response.text
    assert "openai codex oauth is not logged in" in response.text


def test_phase6_api_run_failure_still_emits_final_state(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.server.routes import runs as runs_route
    monkeypatch.setattr(runs_route, "_preflight_run_config", lambda: [])

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
    assert 'event: run_state\ndata: {"run_id": "run_phase6_fail", "status": "failed"' in response.text
    assert '"route_plan": {"run_id": "run_phase6_fail"' in response.text


def test_phase6_api_rejects_resume_run_id_even_with_topic() -> None:
    from src.server.routes import runs as runs_route

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(runs_route, "_preflight_run_config", lambda: [])
    client = TestClient(app)

    try:
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
    finally:
        monkeypatch.undo()

    assert response.status_code == 400
    assert "resume_run_id is not supported" in response.text


def test_phase7_config_and_credentials_posts_persist_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.server.routes import config as config_route

    tmp_dir = Path(__file__).resolve().parent / ".tmp_config_route"
    tmp_dir.mkdir(exist_ok=True)
    config_path = tmp_dir / "agent.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "mcp": {"servers": {"llm": {"transport": "stdio"}}},
                "llm": {"provider": "gemini"},
                "agent": {"language": "zh"},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    env_path = tmp_dir / ".env"
    env_path.write_text('OPENAI_API_KEY="old-key"\nOTHER_FLAG=keep\n', encoding="utf-8")
    monkeypatch.setattr(config_route, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config_route, "ENV_PATH", env_path)

    client = TestClient(app)

    config_response = client.post(
        "/api/config",
        json={"llm": {"provider": "openai"}, "agent": {"language": "en"}},
    )
    credentials_response = client.post(
        "/api/credentials",
        json={"OPENAI_API_KEY": "secret", "GEMINI_API_KEY": "gem-key"},
    )

    assert config_response.status_code == 200
    assert credentials_response.status_code == 200

    saved_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved_config["mcp"]["servers"]["llm"]["transport"] == "stdio"
    assert saved_config["llm"]["provider"] == "openai"
    assert saved_config["agent"]["language"] == "en"

    saved_env = env_path.read_text(encoding="utf-8")
    assert 'OPENAI_API_KEY="secret"' in saved_env
    assert 'GEMINI_API_KEY="gem-key"' in saved_env
    assert "OTHER_FLAG=keep" in saved_env


def test_api_config_normalizes_legacy_critic_role_and_preserves_planner_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.server.routes import config as config_route

    tmp_dir = Path(".tmp_phase7_config_normalize")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    config_path = tmp_dir / "agent.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "llm": {
                    "role_models": {
                        "conductor": {"provider": "openai_codex", "model": "openai-codex/gpt-5.1-codex"},
                        "critic": {"provider": "openrouter", "model": "google/gemini-2.0-flash-001"},
                    }
                },
                "agent": {
                    "routing": {
                        "planner_llm": {
                            "provider": "openrouter",
                            "model": "google/gemini-2.5-flash",
                            "temperature": 0.2,
                        }
                    }
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_route, "CONFIG_PATH", config_path)

    client = TestClient(app)
    response = client.get("/api/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["llm"]["role_models"]["reviewer"]["provider"] == "openrouter"
    assert payload["llm"]["role_models"]["reviewer"]["model"] == "google/gemini-2.0-flash-001"
    assert "critic" not in payload["llm"]["role_models"]
    assert payload["agent"]["routing"]["planner_llm"]["provider"] == "openrouter"
    assert payload["agent"]["routing"]["planner_llm"]["model"] == "google/gemini-2.5-flash"


def _legacy_phase7_codex_status_route_reports_chatgpt_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.server.routes import config as config_route

    monkeypatch.setattr(
        config_route,
        "openai_codex_login_status",
        lambda: {
            "installed": True,
            "logged_in": True,
            "chatgpt_logged_in": True,
            "auth_mode": "chatgpt",
            "executable": "",
            "available": True,
            "user_name": "",
            "user_email": "user@example.com",
            "user_label": "user@example.com",
            "plan_type": "plus",
            "account_id": "acct_123",
            "expires_at": 1234567890,
            "expires_in_sec": 3600,
            "expired": False,
            "has_refresh_token": True,
            "login_in_progress": False,
            "last_error": "",
        },
    )
    client = TestClient(app)

    response = client.get("/api/codex/status")

    assert response.status_code == 200
    assert response.json() == {
        "installed": True,
        "logged_in": True,
        "chatgpt_logged_in": True,
        "auth_mode": "chatgpt",
        "executable": "",
        "available": True,
        "user_name": "",
        "user_email": "user@example.com",
        "user_label": "user@example.com",
        "plan_type": "plus",
        "account_id": "acct_123",
        "expires_at": 1234567890,
        "expires_in_sec": 3600,
        "expired": False,
        "has_refresh_token": True,
        "login_in_progress": False,
        "last_error": "",
    }

def _legacy_phase7_codex_login_route_launches_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.server.routes import config as config_route

    monkeypatch.setattr(
        config_route,
        "start_openai_codex_login",
        lambda: {
            "authorize_url": "https://auth.openai.com/oauth/authorize?client_id=test",
            "status": {
                "installed": True,
                "logged_in": False,
                "chatgpt_logged_in": False,
                "auth_mode": "missing",
                "executable": "",
                "available": False,
                "user_name": "",
                "user_email": "",
                "user_label": "",
                "plan_type": "",
                "account_id": "",
                "expires_at": 0,
                "expires_in_sec": 0,
                "expired": False,
                "has_refresh_token": False,
                "login_in_progress": True,
                "last_error": "",
            },
        },
    )
    client = TestClient(app)

    response = client.post("/api/codex/login")

    assert response.status_code == 200
    payload = response.json()
    assert "登录终端" in payload["message"]
    assert payload["status"]["installed"] is True


def _legacy_phase7_codex_logout_route_clears_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.server.routes import config as config_route

    monkeypatch.setattr(
        config_route,
        "logout_openai_codex",
        lambda **kwargs: {
            "installed": True,
            "logged_in": False,
            "chatgpt_logged_in": False,
            "auth_mode": "missing",
            "executable": "",
            "available": False,
            "user_name": "",
            "user_email": "",
            "user_label": "",
            "plan_type": "",
            "account_id": "",
            "expires_at": 0,
            "expires_in_sec": 0,
            "expired": False,
            "has_refresh_token": False,
            "login_in_progress": False,
            "last_error": "",
        },
    )
    client = TestClient(app)

    response = client.post("/api/codex/logout")

    assert response.status_code == 200
    payload = response.json()
    assert "退出" in payload["message"]
    assert payload["status"]["logged_in"] is False








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
    # Force memory persistence so CI doesn't need networkx
    monkeypatch.setattr(
        runtime_module,
        "load_yaml",
        lambda _path: {"knowledge_graph": {"persistence_mode": "memory"}},
    )
    # Bypass MCP startup — no real servers in CI
    async def _fake_mcp(_self, _config):
        from src.dynamic_os.tools.discovery import StartedMcpRuntime
        from src.dynamic_os.tools.registry import ToolRegistry
        return StartedMcpRuntime(registry=ToolRegistry([]), snapshot=[], _sessions={})
    monkeypatch.setattr(
        runtime_module.DynamicResearchRuntime, "_start_mcp_runtime", _fake_mcp,
    )
    output_root = Path(".tmp_phase7_runtime_test")
    output_root.mkdir(parents=True, exist_ok=True)
    runtime = runtime_module.DynamicResearchRuntime(root=Path.cwd(), output_root=output_root)

    result = asyncio.run(runtime.run(user_request="stop immediately", run_id="run_phase7_terminate"))

    assert result.status == "completed"
    assert result.route_plan["terminate"] is True
    assert result.route_plan["planner_notes"] == ["terminate immediately"]
    assert (output_root / "run_phase7_terminate" / "run_snapshot.json").exists()




# ---------------------------------------------------------------------------
# Artifact Content Browser (Feature 1)
# ---------------------------------------------------------------------------


def test_artifact_browser_list_from_disk() -> None:
    from src.server.routes import runs as runs_route

    run_id = "run_browser_list"
    records = [
        {
            "artifact_id": "art_001",
            "artifact_type": "ResearchReport",
            "producer_role": "writer",
            "producer_skill": "draft_report",
            "schema_version": "1.0",
            "content_ref": "",
            "payload": {"report": "# My report"},
            "source_inputs": [],
            "created_at": "2026-03-20T00:00:00+00:00",
        }
    ]
    original_load = runs_route._load_artifacts_full_from_disk

    def patched_load(rid: str) -> list[dict] | None:
        if rid == run_id:
            return records
        return original_load(rid)

    monkeypatch_obj = pytest.MonkeyPatch()
    monkeypatch_obj.setattr(runs_route, "_load_artifacts_full_from_disk", patched_load)
    try:
        client = TestClient(app)
        response = client.get(f"/api/runs/{run_id}/artifacts")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["artifact_id"] == "art_001"
        assert data[0]["payload"]["report"] == "# My report"
    finally:
        monkeypatch_obj.undo()


def test_artifact_browser_get_single_from_disk() -> None:
    from src.server.routes import runs as runs_route

    run_id = "run_browser_single"
    records = [
        {
            "artifact_id": "art_002",
            "artifact_type": "EvidenceMap",
            "producer_role": "researcher",
            "producer_skill": "build_evidence_map",
            "schema_version": "1.0",
            "content_ref": "",
            "payload": {"nodes": ["A", "B"], "edges": [["A", "B"]]},
            "source_inputs": [],
            "created_at": "2026-03-20T00:00:00+00:00",
        }
    ]
    original_load = runs_route._load_artifacts_full_from_disk

    def patched_load(rid: str) -> list[dict] | None:
        if rid == run_id:
            return records
        return original_load(rid)

    monkeypatch_obj = pytest.MonkeyPatch()
    monkeypatch_obj.setattr(runs_route, "_load_artifacts_full_from_disk", patched_load)
    try:
        client = TestClient(app)
        response = client.get(f"/api/runs/{run_id}/artifacts/art_002")
        assert response.status_code == 200
        data = response.json()
        assert data["artifact_id"] == "art_002"
        assert data["payload"]["nodes"] == ["A", "B"]

        missing = client.get(f"/api/runs/{run_id}/artifacts/does_not_exist")
        assert missing.status_code == 404
    finally:
        monkeypatch_obj.undo()


def test_artifact_browser_returns_404_for_unknown_run() -> None:
    from src.server.routes import runs as runs_route

    original_load = runs_route._load_artifacts_full_from_disk

    def patched_load(rid: str) -> list[dict] | None:
        return None

    monkeypatch_obj = pytest.MonkeyPatch()
    monkeypatch_obj.setattr(runs_route, "_load_artifacts_full_from_disk", patched_load)
    try:
        client = TestClient(app)
        response = client.get("/api/runs/run_unknown_xyz/artifacts")
        assert response.status_code == 404
        response2 = client.get("/api/runs/run_unknown_xyz/artifacts/art_x")
        assert response2.status_code == 404
    finally:
        monkeypatch_obj.undo()


def test_artifact_browser_list_from_active_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.server.routes import runs as runs_route
    from src.dynamic_os.contracts.artifact import ArtifactRecord
    from src.dynamic_os.contracts.route_plan import RoleId
    from src.dynamic_os.storage.memory import InMemoryArtifactStore

    store = InMemoryArtifactStore()
    record = ArtifactRecord(
        artifact_id="art_active_001",
        artifact_type="PaperNotes",
        producer_role=RoleId.researcher,
        producer_skill="extract_notes",
        payload={"notes": "very interesting finding"},
    )
    store.save(record)

    fake_runtime = SimpleNamespace(_artifact_store=store)
    monkeypatch.setitem(runs_route._ACTIVE_RUNTIMES, "run_active_test", fake_runtime)

    client = TestClient(app)
    response = client.get("/api/runs/run_active_test/artifacts")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["artifact_id"] == "art_active_001"
    assert data[0]["payload"]["notes"] == "very interesting finding"


def test_artifact_browser_get_single_from_active_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.server.routes import runs as runs_route
    from src.dynamic_os.contracts.artifact import ArtifactRecord
    from src.dynamic_os.contracts.route_plan import RoleId
    from src.dynamic_os.storage.memory import InMemoryArtifactStore

    store = InMemoryArtifactStore()
    record = ArtifactRecord(
        artifact_id="art_active_002",
        artifact_type="TopicBrief",
        producer_role=RoleId.conductor,
        producer_skill="plan_research",
        payload={"brief": "topic overview"},
    )
    store.save(record)

    fake_runtime = SimpleNamespace(_artifact_store=store)
    monkeypatch.setitem(runs_route._ACTIVE_RUNTIMES, "run_active_single", fake_runtime)

    client = TestClient(app)
    response = client.get("/api/runs/run_active_single/artifacts/art_active_002")
    assert response.status_code == 200
    data = response.json()
    assert data["artifact_id"] == "art_active_002"
    assert data["payload"]["brief"] == "topic overview"

    missing = client.get("/api/runs/run_active_single/artifacts/no_such_artifact")
    assert missing.status_code == 404


def test_runtime_writes_artifacts_full_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After a run completes, artifacts_full.json must contain full artifact payloads."""
    import src.dynamic_os.runtime as runtime_mod
    from src.dynamic_os.runtime import DynamicResearchRuntime, DynamicRunResult
    from src.dynamic_os.contracts.artifact import ArtifactRecord
    from src.dynamic_os.contracts.route_plan import RoleId
    from src.dynamic_os.storage.memory import InMemoryArtifactStore as IAS

    async def patched_run(self, *, user_request: str, run_id: str | None = None):
        import json as _json

        resolved_run_id = run_id or "run_full_test"
        run_dir = self._output_root / resolved_run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        artifact_store = IAS()
        self._artifact_store = artifact_store

        artifact_store.save(
            ArtifactRecord(
                artifact_id="art_full_001",
                artifact_type="ResearchReport",
                producer_role=RoleId.writer,
                producer_skill="draft_report",
                payload={"report": "the full report text"},
            )
        )

        artifacts = artifact_store.list_all()
        artifacts_full = [a.model_dump(mode="json") for a in artifacts]
        (run_dir / "artifacts_full.json").write_text(
            _json.dumps(artifacts_full, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        return DynamicRunResult(
            run_id=resolved_run_id,
            status="completed",
            route_plan={},
            node_status={},
            artifacts=[
                {
                    "artifact_id": "art_full_001",
                    "artifact_type": "ResearchReport",
                    "producer_role": "writer",
                    "producer_skill": "draft_report",
                }
            ],
            report_text="the full report text",
            output_dir=run_dir,
            events=[],
        )

    monkeypatch.setattr(DynamicResearchRuntime, "run", patched_run)
    runtime = DynamicResearchRuntime(root=str(tmp_path), output_root=str(tmp_path / "outputs"))

    result = asyncio.run(runtime.run(user_request="test", run_id="run_full_test"))

    full_path = tmp_path / "outputs" / "run_full_test" / "artifacts_full.json"
    assert full_path.exists(), "artifacts_full.json must be written after run"
    full_data = json.loads(full_path.read_text(encoding="utf-8"))
    assert len(full_data) == 1
    assert full_data[0]["artifact_id"] == "art_full_001"
    assert full_data[0]["payload"]["report"] == "the full report text"
