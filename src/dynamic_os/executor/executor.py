"""顶层执行器模块 —— 驱动"规划-执行-观测-重规划"主循环。

Executor 是 Dynamic OS 的核心调度引擎，负责：
1. 调用 Planner 生成执行计划（RoutePlan）
2. 按 DAG 拓扑序逐节点执行
3. 收集观测结果，判断是否需要 replan
4. 管理预算检查和运行终止
5. 处理人机交互（HITL）节点的暂停/恢复

主循环：plan → execute → observe → replan（如需要）→ plan → ...
直到 Planner 标记 terminate 或预算耗尽。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from src.dynamic_os.artifact_refs import make_artifact
from src.dynamic_os.contracts.artifact import ArtifactRecord, now_iso as _now_iso
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
from src.dynamic_os.planner.planner import Planner, PlannerOutputError
from src.dynamic_os.policy.engine import BudgetExceededError, PolicyEngine


# 事件接收回调类型，用于将事件推送到前端（SSE）或日志系统
EventSink = Callable[[object], None]


def _artifact_ref(record) -> str:
    """将产物记录转为标准引用字符串 'artifact:<type>:<id>'。"""
    return f"artifact:{record.artifact_type}:{record.artifact_id}"


@dataclass(frozen=True)
class PlanExecutionResult:
    """单次计划执行的结果。

    包含该轮执行产生的所有观测，以及是否需要触发 replan。
    """

    # 本轮执行产生的所有观测结果
    observations: list[Observation]
    # 是否需要触发重新规划
    should_replan: bool
    # 重新规划的原因描述
    replan_reason: str


@dataclass(frozen=True)
class ExecutorRunResult:
    """整个运行的最终结果。

    运行终止后返回，包含所有产物、观测和事件的完整记录。
    """

    # 运行唯一标识
    run_id: str
    # 最终产出的所有产物引用
    final_artifacts: list[str]
    # 运行期间的所有观测结果
    observations: list[Observation]
    # 运行期间发布的所有事件
    events: list[object]
    # 终止原因（如 "planner_terminated"、预算超限等）
    termination_reason: str
    # 总共经历的规划迭代次数
    planning_iterations: int


class Executor:
    """顶层执行器 —— 管理"规划→执行→观测→重规划"主循环。

    协调 Planner（规划器）和 NodeRunner（节点执行器），
    在预算约束下驱动研究任务从开始到完成。
    """

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
        self._planner = planner           # 规划器，生成 RoutePlan
        self._node_runner = node_runner     # 节点执行器，运行单个节点
        self._artifact_store = artifact_store     # 产物存储
        self._observation_store = observation_store  # 观测存储
        self._policy = policy               # 策略引擎，执行预算和权限检查
        self._event_sink = event_sink       # 事件推送回调
        self._events: list[object] = []     # 运行期间收集的所有事件
        self._hitl_event: asyncio.Event | None = None  # HITL 异步等待信号
        self._hitl_response: str = ""       # 用户的 HITL 回复内容

    def submit_hitl_response(self, response: str) -> None:
        """接收用户的人机交互回复，唤醒等待中的 HITL 节点。"""
        self._hitl_response = response
        if self._hitl_event is not None:
            self._hitl_event.set()

    async def run(self, *, user_request: str, run_id: str) -> ExecutorRunResult:
        """执行主循环：反复调用 Planner 和 execute_plan，直到终止。"""
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
                execution = await self.execute_plan(plan, user_request=user_request)
            except BudgetExceededError as exc:
                return self._terminate(
                    run_id=run_id,
                    reason=str(exc),
                    observations=observations,
                    planning_iterations=planning_iteration + 1,
                )

            observations.extend(execution.observations)

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

    async def execute_plan(self, plan: RoutePlan, *, user_request: str = "") -> PlanExecutionResult:
        """执行单个路由计划中的所有节点。

        按 DAG 拓扑序选择就绪节点执行。如果节点执行触发 replan，
        立即中断当前计划执行并返回。无法执行也无法跳过的节点会抛出异常。
        """
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
                        result = await self._node_runner.run_node(run_id=plan.run_id, node=node, user_request=user_request)
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
        """处理人机交互（HITL）节点。

        向前端发送问题，异步等待用户回复，
        将回复封装为 UserGuidance 产物供下游节点使用。
        """
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

    def _is_ready(self, node: PlanNode, edges: list[PlanEdge], statuses: dict[str, NodeStatus]) -> bool:
        """判断节点是否满足所有入边条件，可以开始执行。"""
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
        """判断节点是否因上游条件不满足而可以被跳过（所有上游已完成但条件不匹配）。"""
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
        """终止运行，发布 RunTerminateEvent 并返回最终结果。"""
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
        """为 Planner 输出错误构造一个失败观测记录。"""
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
        """验证 Planner 返回的计划 run_id 与当前运行一致。"""
        if plan.run_id != run_id:
            raise PlannerOutputError(
                f"planner output run_id mismatch: expected {run_id}, got {plan.run_id}"
            )

    def _emit(self, event: object) -> None:
        """发布事件：记录到本地列表，并通过 event_sink 推送到外部。"""
        self._events.append(event)
        if self._event_sink is not None:
            self._event_sink(event)
