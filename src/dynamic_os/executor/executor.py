from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from src.dynamic_os.artifact_refs import make_artifact
from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.events import (
    ArtifactEvent,
    HitlRequestEvent,
    HitlResponseEvent,
    NodeStatusEvent,
    ObservationEvent,
    PlanUpdateEvent,
    ReplanEvent,
    RunTerminateEvent,
)
from src.dynamic_os.contracts.observation import ErrorType, NodeStatus, Observation
from src.dynamic_os.contracts.route_plan import EdgeCondition, PlanEdge, PlanNode, RoleId, RoutePlan
from src.dynamic_os.executor.node_runner import NodeExecutionResult, NodeRunner
from src.dynamic_os.planner import decide_termination
from src.dynamic_os.planner.routing import derive_role_routing_policy
from src.dynamic_os.planner.planner import Planner, PlannerOutputError
from src.dynamic_os.policy.engine import BudgetExceededError, PolicyEngine


EventSink = Callable[[object], None]


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _artifact_ref(record) -> str:
    return f"artifact:{record.artifact_type}:{record.artifact_id}"


@dataclass(frozen=True)
class PlanExecutionResult:
    observations: list[Observation]
    should_replan: bool
    replan_reason: str


@dataclass(frozen=True)
class ExecutorRunResult:
    run_id: str
    final_artifacts: list[str]
    observations: list[Observation]
    events: list[object]
    termination_reason: str
    planning_iterations: int


class Executor:
    def __init__(
        self,
        *,
        planner: Planner,
        node_runner: NodeRunner,
        artifact_store,
        observation_store,
        policy: PolicyEngine,
        event_sink: EventSink | None = None,
    ) -> None:
        self._planner = planner
        self._node_runner = node_runner
        self._artifact_store = artifact_store
        self._observation_store = observation_store
        self._policy = policy
        self._event_sink = event_sink
        self._events: list[object] = []
        self._hitl_event: asyncio.Event | None = None
        self._hitl_response: str = ""

    def submit_hitl_response(self, response: str) -> None:
        self._hitl_response = response
        if self._hitl_event is not None:
            self._hitl_event.set()

    async def run(self, *, user_request: str, run_id: str) -> ExecutorRunResult:
        planning_iteration = 0
        observations: list[Observation] = []

        while True:
            try:
                self._policy.record_planning_iteration()
                plan = await self._planner.plan(
                    run_id=run_id,
                    user_request=user_request,
                    planning_iteration=planning_iteration,
                    budget_snapshot=self._policy.snapshot(),
                )
                self._validate_plan_identity(plan=plan, run_id=run_id)
            except BudgetExceededError as exc:
                return self._terminate(run_id=run_id, reason=str(exc), observations=observations, planning_iterations=planning_iteration)
            except PlannerOutputError as exc:
                observation = self._planner_error_observation(planning_iteration=planning_iteration, detail=str(exc))
                observations.append(observation)
                self._observation_store.save(observation)
                self._emit(
                    ObservationEvent(
                        ts=_now_iso(),
                        run_id=run_id,
                        observation=observation.model_dump(mode="json"),
                    )
                )
                return self._terminate(run_id=run_id, reason=str(exc), observations=observations, planning_iterations=planning_iteration)

            self._emit(
                PlanUpdateEvent(
                    ts=_now_iso(),
                    run_id=run_id,
                    planning_iteration=planning_iteration,
                    plan=plan.model_dump(mode="json"),
                )
            )

            if plan.terminate and not plan.nodes:
                return self._terminate(
                    run_id=run_id,
                    reason="planner_terminated",
                    observations=observations,
                    planning_iterations=planning_iteration + 1,
                )

            try:
                execution = await self.execute_plan(plan)
            except BudgetExceededError as exc:
                return self._terminate(
                    run_id=run_id,
                    reason=str(exc),
                    observations=observations,
                    planning_iterations=planning_iteration + 1,
                )

            observations.extend(execution.observations)

            if self._should_terminate_after_final_artifact(
                user_request=user_request,
                execution=execution,
            ):
                return self._terminate(
                    run_id=run_id,
                    reason="final_artifact_produced",
                    observations=observations,
                    planning_iterations=planning_iteration + 1,
                )

            if plan.terminate and not execution.should_replan:
                return self._terminate(
                    run_id=run_id,
                    reason="planner_terminated",
                    observations=observations,
                    planning_iterations=planning_iteration + 1,
                )

            if execution.should_replan:
                self._emit(
                    ReplanEvent(
                        ts=_now_iso(),
                        run_id=run_id,
                        reason=execution.replan_reason,
                        previous_iteration=planning_iteration,
                        new_iteration=planning_iteration + 1,
                    )
                )

            planning_iteration += 1

    async def execute_plan(self, plan: RoutePlan) -> PlanExecutionResult:
        pending = {node.node_id for node in plan.nodes}
        statuses: dict[str, NodeStatus] = {}
        observations: list[Observation] = []
        node_map = {node.node_id: node for node in plan.nodes}
        incoming: dict[str, list[PlanEdge]] = {node.node_id: [] for node in plan.nodes}
        for edge in plan.edges:
            incoming[edge.target].append(edge)

        while pending:
            ready_nodes = [
                node
                for node in plan.nodes
                if node.node_id in pending and self._is_ready(node, incoming[node.node_id], statuses)
            ]
            if ready_nodes:
                for node in ready_nodes:
                    if node.role == RoleId.hitl:
                        result = await self._handle_hitl_node(node=node, run_id=plan.run_id)
                    else:
                        result = await self._node_runner.run_node(run_id=plan.run_id, node=node)
                    observations.append(result.observation)
                    statuses[node.node_id] = result.observation.status
                    pending.remove(node.node_id)
                    if result.should_replan:
                        return PlanExecutionResult(
                            observations=observations,
                            should_replan=True,
                            replan_reason=result.observation.what_happened or "node_requested_replan",
                        )
                continue

            skippable = [
                node
                for node in plan.nodes
                if node.node_id in pending and self._is_skippable(node, incoming[node.node_id], statuses)
            ]
            if skippable:
                for node in skippable:
                    statuses[node.node_id] = NodeStatus.skipped
                    pending.remove(node.node_id)
                    self._emit(
                        NodeStatusEvent(
                            ts=_now_iso(),
                            run_id=plan.run_id,
                            node_id=node.node_id,
                            role=node.role.value,
                            status="skipped",
                        )
                    )
                continue

            unresolved = ", ".join(sorted(pending))
            raise RuntimeError(f"route plan has no executable ready nodes: {unresolved}")

        return PlanExecutionResult(observations=observations, should_replan=False, replan_reason="")

    async def _handle_hitl_node(self, *, node: PlanNode, run_id: str) -> NodeExecutionResult:
        self._emit(
            NodeStatusEvent(
                ts=_now_iso(),
                run_id=run_id,
                node_id=node.node_id,
                role=node.role.value,
                status="running",
            )
        )
        context_summary = ", ".join(
            f"{record.artifact_type}:{record.artifact_id}"
            for record in self._artifact_store.list_all()
        )
        question = node.hitl_question or node.goal
        self._emit(
            HitlRequestEvent(
                ts=_now_iso(),
                run_id=run_id,
                node_id=node.node_id,
                question=question,
                context=context_summary,
            )
        )
        self._hitl_event = asyncio.Event()
        self._hitl_response = ""
        await self._hitl_event.wait()
        self._hitl_event = None
        response = self._hitl_response

        artifact = make_artifact(
            node_id=node.node_id,
            artifact_type="UserGuidance",
            producer_role=RoleId.hitl,
            producer_skill="hitl",
            payload={"question": question, "response": response},
        )
        self._artifact_store.save(artifact)
        self._emit(
            ArtifactEvent(
                ts=_now_iso(),
                run_id=run_id,
                artifact_id=artifact.artifact_id,
                artifact_type=artifact.artifact_type,
                producer_role=artifact.producer_role.value,
                producer_skill=artifact.producer_skill,
            )
        )
        self._emit(
            HitlResponseEvent(
                ts=_now_iso(),
                run_id=run_id,
                node_id=node.node_id,
                response=response,
            )
        )
        observation = Observation(
            node_id=node.node_id,
            role=node.role,
            status=NodeStatus.success,
            error_type=ErrorType.none,
            what_happened=f"Human provided guidance: {response[:120]}",
            what_was_tried=["hitl:pause_and_resume"],
            suggested_options=[],
            recommended_action="",
            produced_artifacts=[f"artifact:UserGuidance:{artifact.artifact_id}"],
            confidence=1.0,
            duration_ms=0.0,
        )
        self._observation_store.save(observation)
        self._emit(
            ObservationEvent(
                ts=_now_iso(),
                run_id=run_id,
                observation=observation.model_dump(mode="json"),
            )
        )
        self._emit(
            NodeStatusEvent(
                ts=_now_iso(),
                run_id=run_id,
                node_id=node.node_id,
                role=node.role.value,
                status="success",
            )
        )
        return NodeExecutionResult(
            node=node,
            skill_id="hitl",
            observation=observation,
            artifacts=[artifact],
            should_replan=False,
        )

    def _should_terminate_after_final_artifact(
        self,
        *,
        user_request: str,
        execution: PlanExecutionResult,
    ) -> bool:
        if execution.should_replan:
            return False
        records = list(self._artifact_store.list_all())
        artifact_summaries = [{"artifact_type": record.artifact_type} for record in records]
        if not decide_termination(artifact_summaries):
            return False
        artifact_types = {record.artifact_type for record in records}
        if "ReviewVerdict" in artifact_types:
            return True
        if "ResearchReport" not in artifact_types:
            return False
        routing_policy = derive_role_routing_policy(user_request=user_request, artifacts=records)
        return "review" not in set(routing_policy.intents)

    def _is_ready(self, node: PlanNode, edges: list[PlanEdge], statuses: dict[str, NodeStatus]) -> bool:
        if not edges:
            return True
        for edge in edges:
            source_status = statuses.get(edge.source)
            if source_status is None:
                return False
            if edge.condition == EdgeCondition.on_success and source_status != NodeStatus.success:
                return False
            if edge.condition == EdgeCondition.on_failure and source_status not in {
                NodeStatus.failed,
                NodeStatus.partial,
                NodeStatus.needs_replan,
            }:
                return False
        return True

    def _is_skippable(self, node: PlanNode, edges: list[PlanEdge], statuses: dict[str, NodeStatus]) -> bool:
        if not edges:
            return False
        for edge in edges:
            source_status = statuses.get(edge.source)
            if source_status is None:
                return False
            if source_status not in {
                NodeStatus.success,
                NodeStatus.partial,
                NodeStatus.failed,
                NodeStatus.needs_replan,
                NodeStatus.skipped,
            }:
                return False
        return not self._is_ready(node, edges, statuses)

    def _terminate(
        self,
        *,
        run_id: str,
        reason: str,
        observations: list[Observation],
        planning_iterations: int,
    ) -> ExecutorRunResult:
        final_artifacts = [_artifact_ref(record) for record in self._artifact_store.list_all()]
        self._emit(
            RunTerminateEvent(
                ts=_now_iso(),
                run_id=run_id,
                reason=reason,
                final_artifacts=final_artifacts,
            )
        )
        return ExecutorRunResult(
            run_id=run_id,
            final_artifacts=final_artifacts,
            observations=list(observations),
            events=list(self._events),
            termination_reason=reason,
            planning_iterations=planning_iterations,
        )

    def _planner_error_observation(self, *, planning_iteration: int, detail: str) -> Observation:
        return Observation(
            node_id=f"planner_iteration_{planning_iteration}",
            role="planner",
            status=NodeStatus.failed,
            error_type=ErrorType.llm_error,
            what_happened=detail,
            what_was_tried=["planner:structured_output"],
            suggested_options=["abort"],
            recommended_action="abort",
            confidence=0.0,
            duration_ms=0.0,
        )

    def _validate_plan_identity(self, *, plan: RoutePlan, run_id: str) -> None:
        if plan.run_id != run_id:
            raise PlannerOutputError(
                f"planner output run_id mismatch: expected {run_id}, got {plan.run_id}"
            )

    def _emit(self, event: object) -> None:
        self._events.append(event)
        if self._event_sink is not None:
            self._event_sink(event)
