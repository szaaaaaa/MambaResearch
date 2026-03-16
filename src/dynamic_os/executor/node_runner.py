from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from src.dynamic_os.artifact_refs import artifact_ref_for_record, parse_artifact_ref
from src.dynamic_os.contracts.artifact import ArtifactRecord
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


EventSink = Callable[[object], None]


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()

@dataclass(frozen=True)
class NodeExecutionResult:
    node: PlanNode
    skill_id: str
    observation: Observation
    artifacts: list[ArtifactRecord]
    should_replan: bool


class NodeRunner:
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
    ) -> None:
        self._role_registry = role_registry
        self._skill_registry = skill_registry
        self._artifact_store = artifact_store
        self._observation_store = observation_store
        self._tools = tools
        self._policy = policy
        self._event_sink = event_sink
        self._config = dict(config or {})

    async def run_node(self, *, run_id: str, node: PlanNode) -> NodeExecutionResult:
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
        if len(node.allowed_skills) == 1:
            return self._skill_registry.get(node.allowed_skills[0])

        available_types = {artifact.artifact_type for artifact in input_artifacts}
        candidates: list[tuple[LoadedSkill, int, int]] = []
        for position, skill_id in enumerate(node.allowed_skills):
            loaded_skill = self._skill_registry.get(skill_id)
            required_artifact_types = [
                required_type
                for required_type in loaded_skill.spec.input_contract.required
                if required_type[:1].isupper()
            ]
            if any(required_type not in available_types for required_type in required_artifact_types):
                continue
            output_score = len(set(node.expected_outputs) & set(loaded_skill.spec.output_artifacts))
            candidates.append((loaded_skill, output_score, position))

        if not candidates:
            raise ValueError(
                "没有可执行的技能满足当前节点输入："
                f"{', '.join(node.allowed_skills)}；可用输入类型 {sorted(available_types)}"
            )

        selected, _, _ = max(
            candidates,
            key=lambda item: (item[1], -item[2]),
        )
        return selected

    async def _invoke_skill(
        self,
        *,
        loaded_skill: LoadedSkill,
        run_id: str,
        node: PlanNode,
        input_artifacts: list[ArtifactRecord],
    ) -> SkillOutput:
        ctx = SkillContext(
            skill_id=loaded_skill.spec.id,
            role_id=node.role.value,
            run_id=run_id,
            node_id=node.node_id,
            goal=node.goal,
            input_artifacts=input_artifacts,
            tools=self._tools.with_context(
                run_id=run_id,
                node_id=node.node_id,
                skill_id=loaded_skill.spec.id,
                role_id=node.role.value,
            ).with_permissions(loaded_skill.spec.permissions).with_allowed_tools(loaded_skill.spec.allowed_tools),
            config=self._config,
            timeout_sec=loaded_skill.spec.timeout_sec,
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
        return status.value

    def _emit(self, event: object) -> None:
        if self._event_sink is not None:
            self._event_sink(event)
