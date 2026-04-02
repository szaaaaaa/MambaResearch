"""节点执行器模块 —— 负责单个 PlanNode 的完整执行生命周期。

NodeRunner 是执行器的底层引擎，每次执行一个节点时：
1. 检查预算 → 2. 解析输入产物 → 3. 选择技能 → 4. 权限检查
→ 5. 调用技能 → 6. 收集产物 → 7. 生成观测 → 8. 发布事件

处理的异常类型：
- PolicyViolationError: 权限不足，生成 policy_block 观测
- TimeoutError: 执行超时
- ValueError: 输入产物缺失或类型不匹配
- Exception: 技能内部错误
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from src.dynamic_os.artifact_refs import artifact_ref_for_record, parse_artifact_ref
from src.dynamic_os.contracts.artifact import ArtifactRecord, now_iso as _now_iso
from src.dynamic_os.contracts.events import (
    ArtifactEvent,
    NodeStatusEvent,
    ObservationEvent,
    PolicyBlockEvent,
    SkillInvokeEvent,
)
from src.dynamic_os.contracts.observation import ErrorType, NodeStatus, Observation
from src.dynamic_os.contracts.route_plan import FailurePolicy, PlanNode
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput
from src.dynamic_os.policy.engine import PolicyEngine, PolicyViolationError
from src.dynamic_os.roles.registry import RoleRegistry
from src.dynamic_os.skills.loader import LoadedSkill
from src.dynamic_os.skills.registry import SkillRegistry
from src.dynamic_os.tools.gateway import ToolGateway


# 事件推送回调类型
EventSink = Callable[[object], None]


@dataclass(frozen=True)
class NodeExecutionResult:
    """单个节点的执行结果。

    封装节点执行后的所有信息，Executor 根据此结果
    决定是否 replan 或继续执行下一个节点。
    """

    # 执行的节点定义
    node: PlanNode
    # 实际使用的技能 ID
    skill_id: str
    # 执行产生的观测结果
    observation: Observation
    # 执行产出的产物列表
    artifacts: list[ArtifactRecord]
    # 是否需要触发重新规划
    should_replan: bool


class NodeRunner:
    """节点执行器 —— 管理单节点从输入解析到产物产出的完整流程。

    依赖注入：角色注册表、技能注册表、产物存储、工具网关、策略引擎等
    均通过构造函数注入，保持 NodeRunner 本身无状态。
    """

    def __init__(
        self,
        *,
        role_registry: RoleRegistry,
        skill_registry: SkillRegistry,
        artifact_store,
        observation_store,
        tools: ToolGateway,
        policy: PolicyEngine,
        event_sink: EventSink | None = None,
        config: dict | None = None,
        knowledge_graph=None,
        skill_metrics_store=None,
    ) -> None:
        self._role_registry = role_registry       # 角色注册表，查找角色配置
        self._skill_registry = skill_registry     # 技能注册表，查找和加载技能
        self._artifact_store = artifact_store     # 产物存储，读写产物
        self._observation_store = observation_store  # 观测存储
        self._tools = tools                       # 工具网关，提供外部工具调用能力
        self._policy = policy                     # 策略引擎
        self._event_sink = event_sink             # 事件推送回调
        self._config = dict(config or {})         # 全局配置参数
        self._knowledge_graph = knowledge_graph   # 知识图谱实例
        self._skill_metrics_store = skill_metrics_store  # 技能执行指标存储

    async def run_node(self, *, run_id: str, node: PlanNode, user_request: str = "") -> NodeExecutionResult:
        """执行单个节点的完整流程。

        流程：预算检查 → 解析输入 → 选择技能 → 权限检查 → 调用技能
        → 保存产物 → 生成观测 → 发布事件 → 返回结果。
        """
        self._policy.check_budget()
        self._policy.record_node_execution()
        self._emit(
            NodeStatusEvent(
                ts=_now_iso(),
                run_id=run_id,
                node_id=node.node_id,
                role=node.role.value,
                status="running",
            )
        )

        started_at = time.perf_counter()
        skill_id = node.allowed_skills[0]
        artifacts: list[ArtifactRecord] = []

        try:
            input_artifacts = self._resolve_inputs(node.inputs)
        except ValueError as exc:
            observation = self._build_error_observation(
                node=node,
                skill_id=skill_id,
                error_type=ErrorType.input_missing,
                message=str(exc),
                suggested_options=["fix_inputs", "replan"],
                duration_ms=(time.perf_counter() - started_at) * 1000.0,
            )
            self._emit(
                SkillInvokeEvent(
                    ts=_now_iso(),
                    run_id=run_id,
                    node_id=node.node_id,
                    skill_id=skill_id,
                    phase="error",
                )
            )
            self._observation_store.save(observation)
            self._record_metrics(skill_id, observation)
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
                    status=self._node_status_event_value(observation.status),
                )
            )
            return NodeExecutionResult(
                node=node,
                skill_id=skill_id,
                observation=observation,
                artifacts=[],
                should_replan=observation.status == NodeStatus.needs_replan,
            )

        try:
            self._skill_registry.validate_role_assignment(
                node.role.value,
                node.allowed_skills,
                self._role_registry,
            )
            loaded_skill = self._select_skill(node=node, input_artifacts=input_artifacts)
            skill_id = loaded_skill.spec.id
            self._policy.ensure_skill_permissions(loaded_skill.spec.permissions)
            self._emit(
                SkillInvokeEvent(
                    ts=_now_iso(),
                    run_id=run_id,
                    node_id=node.node_id,
                    skill_id=skill_id,
                    phase="start",
                )
            )
            output = await self._invoke_skill(
                loaded_skill=loaded_skill,
                run_id=run_id,
                node=node,
                input_artifacts=input_artifacts,
                user_request=user_request,
            )
            artifacts = list(output.output_artifacts)
            for artifact in artifacts:
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

            observation = self._build_output_observation(
                node=node,
                skill_id=skill_id,
                output=output,
                artifacts=artifacts,
                duration_ms=(time.perf_counter() - started_at) * 1000.0,
            )
            self._emit(
                SkillInvokeEvent(
                    ts=_now_iso(),
                    run_id=run_id,
                    node_id=node.node_id,
                    skill_id=skill_id,
                    phase="end" if output.success else "error",
                )
            )
        except PolicyViolationError as exc:
            observation = self._build_error_observation(
                node=node,
                skill_id=skill_id,
                error_type=ErrorType.policy_block,
                message=str(exc),
                suggested_options=["adjust_policy", "replan"],
                duration_ms=(time.perf_counter() - started_at) * 1000.0,
            )
            self._emit(
                PolicyBlockEvent(
                    ts=_now_iso(),
                    run_id=run_id,
                    blocked_action=skill_id,
                    reason=str(exc),
                )
            )
            self._emit(
                SkillInvokeEvent(
                    ts=_now_iso(),
                    run_id=run_id,
                    node_id=node.node_id,
                    skill_id=skill_id,
                    phase="error",
                )
            )
        except TimeoutError as exc:
            observation = self._build_error_observation(
                node=node,
                skill_id=skill_id,
                error_type=ErrorType.timeout,
                message=str(exc),
                suggested_options=["retry_node", "replan"],
                duration_ms=(time.perf_counter() - started_at) * 1000.0,
            )
            self._emit(
                SkillInvokeEvent(
                    ts=_now_iso(),
                    run_id=run_id,
                    node_id=node.node_id,
                    skill_id=skill_id,
                    phase="error",
                )
            )
        except Exception as exc:
            observation = self._build_error_observation(
                node=node,
                skill_id=skill_id,
                error_type=ErrorType.skill_error,
                message=str(exc),
                suggested_options=["choose_different_skill", "replan"],
                duration_ms=(time.perf_counter() - started_at) * 1000.0,
            )
            self._emit(
                SkillInvokeEvent(
                    ts=_now_iso(),
                    run_id=run_id,
                    node_id=node.node_id,
                    skill_id=skill_id,
                    phase="error",
                )
            )

        self._observation_store.save(observation)
        self._record_metrics(skill_id, observation)
        self._maybe_refresh_registry(artifacts)
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
                status=self._node_status_event_value(observation.status),
            )
        )
        return NodeExecutionResult(
            node=node,
            skill_id=skill_id,
            observation=observation,
            artifacts=artifacts,
            should_replan=observation.status == NodeStatus.needs_replan,
        )

    def _resolve_inputs(self, references: list[str]) -> list[ArtifactRecord]:
        """将产物引用字符串列表解析为实际的 ArtifactRecord 列表。

        验证每个引用的产物存在且类型匹配，不满足则抛出 ValueError。
        """
        artifacts: list[ArtifactRecord] = []
        for reference in references:
            artifact_type, artifact_id = parse_artifact_ref(reference)
            record = self._artifact_store.get(artifact_id)
            if record is None:
                raise ValueError(f"缺少输入产物：{artifact_id}")
            if record.artifact_type != artifact_type:
                raise ValueError(f"输入产物类型不匹配：{artifact_id}，期望 {artifact_type}")
            artifacts.append(record)
        return artifacts

    def _select_skill(self, *, node: PlanNode, input_artifacts: list[ArtifactRecord]) -> LoadedSkill:
        """按 allowed_skills 的顺序选择第一个输入满足的技能（顺序即优先级，由 planner 决定）。"""
        if len(node.allowed_skills) == 1:
            return self._skill_registry.get(node.allowed_skills[0])

        available_types = {artifact.artifact_type for artifact in input_artifacts}

        for skill_id in node.allowed_skills:
            loaded_skill = self._skill_registry.get(skill_id)
            required_artifact_types = [
                required_type
                for required_type in loaded_skill.spec.input_contract.required
                if required_type[:1].isupper()
            ]
            if all(required_type in available_types for required_type in required_artifact_types):
                return loaded_skill

        raise ValueError(
            "没有可执行的技能满足当前节点输入："
            f"{', '.join(node.allowed_skills)}；可用输入类型 {sorted(available_types)}"
        )

    async def _invoke_skill(
        self,
        *,
        loaded_skill: LoadedSkill,
        run_id: str,
        node: PlanNode,
        input_artifacts: list[ArtifactRecord],
        user_request: str = "",
    ) -> SkillOutput:
        """构造 SkillContext 并调用技能的 run 函数。

        为技能配置工具网关（带上下文、权限、允许工具白名单），
        组装完整的 SkillContext 后执行技能。
        """
        skill_config = dict(self._config)
        if loaded_skill.spec.id == "draft_report":
            skill_config["_cite_keys_map"] = self._collect_cite_keys_map()
        ctx = SkillContext(
            skill_id=loaded_skill.spec.id,
            role_id=node.role.value,
            run_id=run_id,
            node_id=node.node_id,
            goal=node.goal,
            user_request=user_request,
            input_artifacts=input_artifacts,
            tools=self._tools.with_context(
                run_id=run_id,
                node_id=node.node_id,
                skill_id=loaded_skill.spec.id,
                role_id=node.role.value,
            ).with_permissions(loaded_skill.spec.permissions).with_allowed_tools(loaded_skill.spec.allowed_tools),
            config=skill_config,
            timeout_sec=loaded_skill.spec.timeout_sec,
            knowledge_graph=self._knowledge_graph,
        )
        return await loaded_skill.runner(ctx)

    def _build_output_observation(
        self,
        *,
        node: PlanNode,
        skill_id: str,
        output: SkillOutput,
        artifacts: list[ArtifactRecord],
        duration_ms: float,
    ) -> Observation:
        """根据技能执行输出构造观测结果。

        判断逻辑：
        - 成功 + 产出完整 → NodeStatus.success
        - 成功 + 产出不完整 → partial 或 needs_replan（取决于 failure_policy）
        - 失败 → needs_replan 或 failed（取决于 failure_policy）
        """
        produced_types = {artifact.artifact_type for artifact in artifacts}
        missing_outputs = [artifact_type for artifact_type in node.expected_outputs if artifact_type not in produced_types]
        if output.success and not missing_outputs:
            status = NodeStatus.success
            error_type = ErrorType.none
            message = "技能执行成功"
            suggested_options: list[str] = []
        elif output.success:
            status = NodeStatus.partial if node.failure_policy != FailurePolicy.replan else NodeStatus.needs_replan
            error_type = ErrorType.none
            message = f"缺少预期产物类型：{', '.join(missing_outputs)}"
            suggested_options = ["replan", "choose_different_skill"]
        else:
            status = NodeStatus.needs_replan if node.failure_policy == FailurePolicy.replan else NodeStatus.failed
            error_type = ErrorType.skill_error
            message = output.error or "技能返回了失败结果"
            suggested_options = ["choose_different_skill", "replan"]
        confidence = output.metadata.get("confidence", 1.0)
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 1.0
        return Observation(
            node_id=node.node_id,
            role=node.role,
            status=status,
            error_type=error_type,
            what_happened=message,
            what_was_tried=[f"skill:{skill_id}"],
            suggested_options=suggested_options,
            recommended_action="replan" if status in {NodeStatus.partial, NodeStatus.needs_replan} else "",
            produced_artifacts=[artifact_ref_for_record(artifact) for artifact in artifacts],
            confidence=max(0.0, min(1.0, confidence_value)),
            duration_ms=duration_ms,
        )

    def _collect_cite_keys_map(self) -> dict[str, str]:
        """收集所有 SourceSet 产物中的引用键映射（cite_key → 论文标题）。

        专用于 draft_report 技能，为报告生成提供引文索引。
        """
        from src.dynamic_os.runtime import _make_cite_key

        key_map: dict[str, str] = {}
        seen_keys: set[str] = set()
        seen_papers: set[str] = set()
        for record in self._artifact_store.list_all():
            if record.artifact_type != "SourceSet":
                continue
            for source in record.payload.get("sources", []):
                title = str(source.get("title", "")).strip()
                if not title:
                    continue
                paper_id = str(source.get("paper_id", "")).strip()
                dedup_id = paper_id or title.lower()
                if dedup_id in seen_papers:
                    continue
                seen_papers.add(dedup_id)
                key = _make_cite_key(source, seen_keys)
                key_map[key] = title
        return key_map

    def _record_metrics(self, skill_id: str, observation: Observation) -> None:
        """记录技能执行指标（状态、置信度、耗时）到指标存储。"""
        if self._skill_metrics_store is not None:
            self._skill_metrics_store.record_execution(
                skill_id=skill_id,
                status=observation.status.value,
                confidence=observation.confidence,
                duration_ms=observation.duration_ms,
            )

    def _maybe_refresh_registry(self, artifacts: list[ArtifactRecord]) -> None:
        """如果产物标记了 requires_registry_refresh，刷新技能注册表。

        用于技能进化场景：新技能被动态创建后，需要刷新注册表以使其可用。
        """
        for artifact in artifacts:
            if artifact.payload.get("requires_registry_refresh"):
                self._skill_registry.refresh()
                return

    def _build_error_observation(
        self,
        *,
        node: PlanNode,
        skill_id: str,
        error_type: ErrorType,
        message: str,
        suggested_options: list[str],
        duration_ms: float,
    ) -> Observation:
        """为错误情况构造失败观测，状态由节点的 failure_policy 决定。"""
        status = NodeStatus.needs_replan if node.failure_policy == FailurePolicy.replan else NodeStatus.failed
        return Observation(
            node_id=node.node_id,
            role=node.role,
            status=status,
            error_type=error_type,
            what_happened=message,
            what_was_tried=[f"skill:{skill_id}"],
            suggested_options=suggested_options,
            recommended_action="replan" if status == NodeStatus.needs_replan else "abort",
            confidence=0.0,
            duration_ms=duration_ms,
        )

    def _node_status_event_value(self, status: NodeStatus) -> str:
        """将 NodeStatus 枚举转为事件中使用的字符串值。"""
        return status.value

    def _emit(self, event: object) -> None:
        """通过 event_sink 回调发布事件。"""
        if self._event_sink is not None:
            self._event_sink(event)
