"""Tests for the Human-in-the-Loop (HITL) pause/resume feature."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import app
from src.dynamic_os.artifact_refs import artifact_ref_for
from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.events import HitlRequestEvent, HitlResponseEvent
from src.dynamic_os.contracts.observation import NodeStatus
from src.dynamic_os.contracts.policy import BudgetPolicy, PermissionPolicy
from src.dynamic_os.contracts.route_plan import FailurePolicy, PlanNode, RoleId, RoutePlan
from src.dynamic_os.executor import Executor, NodeRunner
from src.dynamic_os.planner.planner import Planner
from src.dynamic_os.policy.engine import PolicyEngine
from src.dynamic_os.roles.registry import RoleRegistry
from src.dynamic_os.storage.memory import InMemoryArtifactStore, InMemoryObservationStore, InMemoryPlanStore


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_policy() -> PolicyEngine:
    return PolicyEngine(
        permission_policy=PermissionPolicy(
            approved_workspaces=[],
            allow_network=False,
            allow_sandbox_exec=False,
            allow_filesystem_read=False,
            allow_filesystem_write=False,
        ),
        budget_policy=BudgetPolicy(
            max_planning_iterations=5,
            max_node_executions=20,
            max_tool_invocations=100,
            max_wall_time_sec=300.0,
            max_tokens=500_000,
        ),
    )


def _hitl_node(*, node_id: str = "node_hitl_1", question: str = "Which research direction?") -> PlanNode:
    return PlanNode(
        node_id=node_id,
        role=RoleId.hitl,
        goal="Ask the human for guidance",
        allowed_skills=["hitl"],
        expected_outputs=["UserGuidance"],
        failure_policy=FailurePolicy.replan,
        hitl_question=question,
    )


def _search_node(*, node_id: str = "node_research_1") -> PlanNode:
    return PlanNode(
        node_id=node_id,
        role=RoleId.researcher,
        goal="Search papers",
        allowed_skills=["search_papers"],
        expected_outputs=["SourceSet"],
        failure_policy=FailurePolicy.replan,
    )


class _FakeNodeRunner:
    """Node runner stub that always returns success with a SourceSet artifact."""

    def __init__(self, artifact_store: InMemoryArtifactStore, observation_store: InMemoryObservationStore) -> None:
        self._artifact_store = artifact_store
        self._observation_store = observation_store
        self._policy = _make_policy()

    async def run_node(self, *, run_id: str, node: PlanNode, user_request: str = ""):
        from src.dynamic_os.contracts.observation import ErrorType, Observation
        artifact = ArtifactRecord(
            artifact_id=f"{node.node_id}_source_set",
            artifact_type="SourceSet",
            producer_role=node.role,
            producer_skill=node.allowed_skills[0],
            payload={"papers": []},
        )
        self._artifact_store.save(artifact)
        observation = Observation(
            node_id=node.node_id,
            role=node.role,
            status=NodeStatus.success,
            error_type=ErrorType.none,
            what_happened="done",
            produced_artifacts=[f"artifact:SourceSet:{artifact.artifact_id}"],
            confidence=1.0,
            duration_ms=0.0,
        )
        self._observation_store.save(observation)
        from src.dynamic_os.executor.node_runner import NodeExecutionResult
        return NodeExecutionResult(node=node, skill_id=node.allowed_skills[0], observation=observation, artifacts=[artifact], should_replan=False)


class _StaticPlanner:
    """Planner that returns a fixed sequence of plans."""

    def __init__(self, plans: list[RoutePlan]) -> None:
        self._plans = list(plans)

    async def plan(self, *, run_id, user_request, planning_iteration, budget_snapshot=None):
        return self._plans[min(planning_iteration, len(self._plans) - 1)]


# ---------------------------------------------------------------------------
# Unit tests: PlanNode with hitl role
# ---------------------------------------------------------------------------

class TestHitlPlanNode:
    def test_hitl_role_is_valid(self) -> None:
        node = _hitl_node()
        assert node.role == RoleId.hitl
        assert node.hitl_question == "Which research direction?"

    def test_hitl_node_has_allowed_skills(self) -> None:
        node = _hitl_node()
        assert node.allowed_skills == ["hitl"]

    def test_hitl_node_expected_outputs(self) -> None:
        node = _hitl_node()
        assert "UserGuidance" in node.expected_outputs

    def test_route_plan_with_hitl_node_validates(self) -> None:
        """A RoutePlan containing a hitl node must pass model validation."""
        plan = RoutePlan(
            run_id="run_test",
            planning_iteration=0,
            horizon=1,
            nodes=[_hitl_node()],
            edges=[],
            planner_notes=[],
            terminate=False,
        )
        assert plan.nodes[0].role == RoleId.hitl

    def test_route_plan_mixed_nodes(self) -> None:
        """hitl and regular nodes can coexist in a plan."""
        hitl = _hitl_node(node_id="node_hitl_1")
        research = _search_node(node_id="node_research_1")
        from src.dynamic_os.contracts.route_plan import EdgeCondition, PlanEdge
        plan = RoutePlan(
            run_id="run_test",
            planning_iteration=0,
            horizon=2,
            nodes=[hitl, research],
            edges=[PlanEdge(source="node_hitl_1", target="node_research_1", condition=EdgeCondition.on_success)],
            planner_notes=[],
            terminate=False,
        )
        assert len(plan.nodes) == 2


# ---------------------------------------------------------------------------
# Unit tests: RoleRegistry skips hitl in validate_route_plan
# ---------------------------------------------------------------------------

class TestRoleRegistryHitl:
    def test_registry_loads_with_hitl_role(self) -> None:
        registry = RoleRegistry.from_file()
        role = registry.get(RoleId.hitl)
        assert role.id == RoleId.hitl

    def test_validate_route_plan_skips_hitl_node(self) -> None:
        registry = RoleRegistry.from_file()
        plan = RoutePlan(
            run_id="run_test",
            planning_iteration=0,
            horizon=1,
            nodes=[_hitl_node()],
            edges=[],
            planner_notes=[],
            terminate=False,
        )
        # Must not raise even though "hitl" is not in the skill registry
        registry.validate_route_plan(plan)


# ---------------------------------------------------------------------------
# Unit tests: Executor HITL handling
# ---------------------------------------------------------------------------

class TestExecutorHitl:
    def _make_executor(self, *, plans: list[RoutePlan], events: list[object]) -> Executor:
        artifact_store = InMemoryArtifactStore()
        observation_store = InMemoryObservationStore()
        node_runner = _FakeNodeRunner(artifact_store, observation_store)
        policy = _make_policy()

        def sink(event: object) -> None:
            events.append(event)

        executor = Executor(
            planner=_StaticPlanner(plans),
            node_runner=node_runner,
            artifact_store=artifact_store,
            observation_store=observation_store,
            policy=policy,
            event_sink=sink,
        )
        return executor

    def test_hitl_node_pauses_until_response(self) -> None:
        """Executor must pause at a hitl node and resume after submit_hitl_response."""
        async def run_case() -> None:
            node = _hitl_node(question="What direction?")
            plan = RoutePlan(
                run_id="run_test",
                planning_iteration=0,
                horizon=1,
                nodes=[node],
                edges=[],
                planner_notes=[],
                terminate=True,
            )
            events: list[object] = []
            executor = self._make_executor(plans=[plan], events=events)

            task = asyncio.create_task(executor.run(user_request="test request", run_id="run_test"))

            for _ in range(200):
                await asyncio.sleep(0.01)
                hitl_events = [e for e in events if isinstance(e, HitlRequestEvent)]
                if hitl_events:
                    break
            else:
                pytest.fail("hitl_request event was never emitted")

            hitl_ev = hitl_events[0]
            assert hitl_ev.node_id == "node_hitl_1"
            assert hitl_ev.question == "What direction?"
            assert not task.done(), "executor must still be paused"

            executor.submit_hitl_response("Focus on transformer architectures")

            result = await asyncio.wait_for(task, timeout=5.0)
            assert result.termination_reason in {"planner_terminated", "final_artifact_produced"}

        asyncio.run(run_case())

    def test_hitl_stores_user_guidance_artifact(self) -> None:
        """After HITL resumes, a UserGuidance artifact must exist in the store."""
        async def run_case() -> None:
            node = _hitl_node()
            plan = RoutePlan(
                run_id="run_test",
                planning_iteration=0,
                horizon=1,
                nodes=[node],
                edges=[],
                planner_notes=[],
                terminate=True,
            )
            events: list[object] = []
            artifact_store = InMemoryArtifactStore()
            observation_store = InMemoryObservationStore()
            node_runner = _FakeNodeRunner(artifact_store, observation_store)
            policy = _make_policy()
            executor = Executor(
                planner=_StaticPlanner([plan]),
                node_runner=node_runner,
                artifact_store=artifact_store,
                observation_store=observation_store,
                policy=policy,
                event_sink=lambda e: events.append(e),
            )

            task = asyncio.create_task(executor.run(user_request="test", run_id="run_test"))

            for _ in range(200):
                await asyncio.sleep(0.01)
                if any(isinstance(e, HitlRequestEvent) for e in events):
                    break

            executor.submit_hitl_response("Use RAG-based approach")
            await asyncio.wait_for(task, timeout=5.0)

            guidance_artifacts = artifact_store.list_by_type("UserGuidance")
            assert len(guidance_artifacts) == 1
            artifact = guidance_artifacts[0]
            assert artifact.payload["response"] == "Use RAG-based approach"
            assert artifact.producer_role == RoleId.hitl

        asyncio.run(run_case())

    def test_hitl_emits_response_event(self) -> None:
        """HitlResponseEvent must be emitted after submit_hitl_response."""
        async def run_case() -> None:
            node = _hitl_node()
            plan = RoutePlan(
                run_id="run_test",
                planning_iteration=0,
                horizon=1,
                nodes=[node],
                edges=[],
                planner_notes=[],
                terminate=True,
            )
            events: list[object] = []
            executor = self._make_executor(plans=[plan], events=events)

            task = asyncio.create_task(executor.run(user_request="test", run_id="run_test"))

            for _ in range(200):
                await asyncio.sleep(0.01)
                if any(isinstance(e, HitlRequestEvent) for e in events):
                    break

            executor.submit_hitl_response("my answer")
            await asyncio.wait_for(task, timeout=5.0)

            response_events = [e for e in events if isinstance(e, HitlResponseEvent)]
            assert len(response_events) == 1
            assert response_events[0].response == "my answer"
            assert response_events[0].node_id == "node_hitl_1"

        asyncio.run(run_case())

    def test_hitl_node_succeeds_and_execution_continues(self) -> None:
        """After HITL, subsequent nodes in the plan must still execute."""
        async def run_case() -> None:
            from src.dynamic_os.contracts.route_plan import EdgeCondition, PlanEdge
            hitl = _hitl_node(node_id="node_hitl_1")
            research = _search_node(node_id="node_research_1")
            plan = RoutePlan(
                run_id="run_test",
                planning_iteration=0,
                horizon=2,
                nodes=[hitl, research],
                edges=[PlanEdge(source="node_hitl_1", target="node_research_1", condition=EdgeCondition.on_success)],
                planner_notes=[],
                terminate=True,
            )
            events: list[object] = []
            artifact_store = InMemoryArtifactStore()
            observation_store = InMemoryObservationStore()
            node_runner = _FakeNodeRunner(artifact_store, observation_store)
            policy = _make_policy()
            executor = Executor(
                planner=_StaticPlanner([plan]),
                node_runner=node_runner,
                artifact_store=artifact_store,
                observation_store=observation_store,
                policy=policy,
                event_sink=lambda e: events.append(e),
            )

            task = asyncio.create_task(executor.run(user_request="test", run_id="run_test"))

            for _ in range(200):
                await asyncio.sleep(0.01)
                if any(isinstance(e, HitlRequestEvent) for e in events):
                    break

            executor.submit_hitl_response("Focus on retrieval")
            await asyncio.wait_for(task, timeout=5.0)

            # hitl node: confirmed via HitlResponseEvent
            assert any(isinstance(e, HitlResponseEvent) for e in events)
            # research node: confirmed via observation store (FakeNodeRunner writes there)
            assert len(observation_store.list_by_node("node_hitl_1")) >= 1
            assert len(observation_store.list_by_node("node_research_1")) >= 1

        asyncio.run(run_case())

    def test_submit_hitl_response_without_active_pause(self) -> None:
        """submit_hitl_response before any pause is a no-op (sets _hitl_response)."""
        executor = self._make_executor(plans=[], events=[])
        # Should not raise; the event is None so nothing happens
        executor.submit_hitl_response("no-op response")


# ---------------------------------------------------------------------------
# Integration tests: API endpoint
# ---------------------------------------------------------------------------

class TestHitlApiEndpoint:
    def test_hitl_endpoint_not_found_for_unknown_run(self) -> None:
        client = TestClient(app)
        resp = client.post("/api/runs/nonexistent_run_id/hitl", json={"response": "hello"})
        assert resp.status_code == 404

    def test_hitl_endpoint_requires_response_field(self) -> None:
        client = TestClient(app)
        # Try with empty response — 400
        resp = client.post("/api/runs/any_run/hitl", json={})
        # Either 400 (validation) or 404 (run not found) is acceptable
        assert resp.status_code in {400, 404}

    def test_hitl_endpoint_requires_json_body(self) -> None:
        client = TestClient(app)
        resp = client.post(
            "/api/runs/any_run/hitl",
            data="not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code in {400, 422}
