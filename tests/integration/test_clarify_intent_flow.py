"""clarify_intent 集成流测试（Task 2：runtime 接入 + HITL 多轮）。

对应 ``docs/plans/2026-04-20-clarify-intent.md`` Task 2 的验收标准：

- AC1/AC4 system-reminder 注入 + 首节点约束：
  ``test_system_reminder_injected_when_no_clarified_intent``
  ``test_system_reminder_dropped_after_clarified_intent``
- AC2 HITL 端到端（ClarificationRequest → pause → submit → ClarificationResponse）：
  ``test_clarification_pause_and_resume_creates_response_artifact``
  ``test_submit_clarification_response_resumes_executor``
- AC3 3 轮上限：
  ``test_round_cap_forces_partial_with_cap_assumption``

所有用例都在进程内构造 Executor / ConfiguredPlannerModel + 注入 fake 依赖，
不触达真实 LLM / MCP / 磁盘。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from src.dynamic_os.artifact_refs import make_artifact
from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.events import HitlRequestEvent
from src.dynamic_os.contracts.observation import ErrorType, NodeStatus, Observation
from src.dynamic_os.contracts.policy import BudgetPolicy, PermissionPolicy
from src.dynamic_os.contracts.route_plan import (
    FailurePolicy,
    PlanNode,
    RoleId,
    RoutePlan,
)
from src.dynamic_os.contracts.skill_io import SkillContext
from src.dynamic_os.executor import Executor
from src.dynamic_os.executor.node_runner import NodeExecutionResult
from src.dynamic_os.policy.engine import PolicyEngine
from src.dynamic_os.runtime import ConfiguredPlannerModel
from src.dynamic_os.skills.builtins.clarify_intent import run as clarify_run
from src.dynamic_os.storage.memory import (
    InMemoryArtifactStore,
    InMemoryObservationStore,
)
from src.dynamic_os.tools.backends import LLMCompletionResult


# ---------------------------------------------------------------------------
# 公用小工具
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
            max_planning_iterations=10,
            max_node_executions=40,
            max_tool_invocations=200,
            max_wall_time_sec=300.0,
            max_tokens=500_000,
        ),
    )


@dataclass
class _CapturingLLMClient:
    """记录每次 ``complete`` 调用的 messages + 返回预设 JSON 文本。"""

    responses: list[str]
    captured_messages: list[list[dict[str, str]]] = field(default_factory=list)

    def complete(
        self,
        *,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_schema: dict | None = None,
    ) -> LLMCompletionResult:
        self.captured_messages.append([dict(m) for m in messages])
        if not self.responses:
            raise RuntimeError("no more canned responses")
        text = self.responses.pop(0)
        return LLMCompletionResult(text=text, usage={"total_tokens": 0})


def _minimal_config() -> dict[str, Any]:
    return {
        "agent": {
            "routing": {
                "planner_llm": {
                    "provider": "openai",
                    "model": "gpt-test",
                    "temperature": 0.2,
                }
            }
        }
    }


# ---------------------------------------------------------------------------
# AC1 / AC4 —— system-reminder 注入与首节点约束
# ---------------------------------------------------------------------------


class TestSystemReminderInjection:
    def test_system_reminder_injected_when_no_clarified_intent(self) -> None:
        """artifact store 无 ClarifiedIntent 时，prompt 必含首节点=clarify_intent 约束。"""
        artifact_store = InMemoryArtifactStore()
        llm = _CapturingLLMClient(responses=['{"run_id":"r","planning_iteration":0,"horizon":1,"nodes":[],"edges":[]}'])
        model = ConfiguredPlannerModel(
            run_id="run_x",
            config=_minimal_config(),
            llm_client=llm,
            policy=_make_policy(),
            artifact_store=artifact_store,
        )

        asyncio.run(model.generate([{"role": "user", "content": "some planner prompt"}], {}))

        assert len(llm.captured_messages) == 1
        system_msg = llm.captured_messages[0][0]
        assert system_msg["role"] == "system"
        content = system_msg["content"]
        # AC1：reminder 可观测
        assert "run_id must be run_x" in content
        # AC4：首节点必须是 conductor+clarify_intent
        assert "clarify_intent" in content
        assert "conductor" in content

    def test_system_reminder_dropped_after_clarified_intent(self) -> None:
        """artifact store 已有 ClarifiedIntent 时，首节点约束消失（允许正常规划）。"""
        artifact_store = InMemoryArtifactStore()
        artifact_store.save(
            make_artifact(
                node_id="node_clarify_1",
                artifact_type="ClarifiedIntent",
                producer_role=RoleId.conductor,
                producer_skill="clarify_intent",
                payload={
                    "inferred_goal": "训练 MLP",
                    "inferred_fields": {},
                    "assumptions": [],
                },
            )
        )
        llm = _CapturingLLMClient(responses=['{"run_id":"r","planning_iteration":0,"horizon":1,"nodes":[],"edges":[]}'])
        model = ConfiguredPlannerModel(
            run_id="run_y",
            config=_minimal_config(),
            llm_client=llm,
            policy=_make_policy(),
            artifact_store=artifact_store,
        )

        asyncio.run(model.generate([{"role": "user", "content": "some planner prompt"}], {}))

        system_msg = llm.captured_messages[0][0]
        content = system_msg["content"]
        assert "run_id must be run_y" in content
        # 已有 ClarifiedIntent，不再强制 clarify_intent 作首节点
        assert "clarify_intent" not in content


# ---------------------------------------------------------------------------
# AC2 —— HITL 端到端：ClarificationRequest pause → submit → ClarificationResponse
# ---------------------------------------------------------------------------


class _StaticPlanner:
    """按 planning_iteration 返回预设 RoutePlan 的假 planner。"""

    def __init__(self, plans: list[RoutePlan]) -> None:
        self._plans = list(plans)

    async def plan(
        self,
        *,
        run_id: str,
        user_request: str,
        planning_iteration: int,
        budget_snapshot=None,
    ) -> RoutePlan:
        idx = min(planning_iteration, len(self._plans) - 1)
        return self._plans[idx]


class _ClarifyIntentNodeRunner:
    """第一次运行产出 ClarificationRequest；后续产出 ClarifiedIntent。"""

    def __init__(self, artifact_store: InMemoryArtifactStore) -> None:
        self._artifact_store = artifact_store
        self.invocations = 0

    async def run_node(self, *, run_id: str, node: PlanNode, user_request: str = "") -> NodeExecutionResult:
        self.invocations += 1
        if self.invocations == 1:
            artifact = make_artifact(
                node_id=node.node_id,
                artifact_type="ClarificationRequest",
                producer_role=RoleId.conductor,
                producer_skill="clarify_intent",
                payload={
                    "round_num": 1,
                    "questions": [
                        {
                            "header": "方向",
                            "question": "哪个方向？",
                            "options": [
                                {"label": "图像", "description": "图像分类"},
                                {"label": "文本", "description": "文本分类"},
                            ],
                        }
                    ],
                },
            )
        else:
            artifact = make_artifact(
                node_id=node.node_id,
                artifact_type="ClarifiedIntent",
                producer_role=RoleId.conductor,
                producer_skill="clarify_intent",
                payload={
                    "inferred_goal": "图像分类 MNIST",
                    "inferred_fields": {"dataset": "MNIST"},
                    "assumptions": [],
                },
            )
        self._artifact_store.save(artifact)
        observation = Observation(
            node_id=node.node_id,
            role=node.role,
            status=NodeStatus.success,
            error_type=ErrorType.none,
            what_happened="clarify_intent done",
            produced_artifacts=[f"artifact:{artifact.artifact_type}:{artifact.artifact_id}"],
            confidence=1.0,
            duration_ms=0.0,
        )
        return NodeExecutionResult(
            node=node,
            skill_id="clarify_intent",
            observation=observation,
            artifacts=[artifact],
            should_replan=False,
        )


def _clarify_node(node_id: str = "node_clarify_1") -> PlanNode:
    return PlanNode(
        node_id=node_id,
        role=RoleId.conductor,
        goal="clarify user intent",
        allowed_skills=["clarify_intent"],
        expected_outputs=["ClarifiedIntent", "ClarificationRequest"],
        failure_policy=FailurePolicy.replan,
    )


def _single_node_plan(*, iteration: int, terminate: bool, node_id: str) -> RoutePlan:
    return RoutePlan(
        run_id="run_clarify",
        planning_iteration=iteration,
        horizon=1,
        nodes=[_clarify_node(node_id=node_id)],
        edges=[],
        planner_notes=[],
        terminate=terminate,
    )


class TestClarificationFlow:
    def test_clarification_pause_and_resume_creates_response_artifact(self) -> None:
        """走完 ClarificationRequest → submit_clarification_response → ClarificationResponse 链路。"""
        async def run_case() -> None:
            artifact_store = InMemoryArtifactStore()
            observation_store = InMemoryObservationStore()
            node_runner = _ClarifyIntentNodeRunner(artifact_store)
            events: list[object] = []
            plans = [
                _single_node_plan(iteration=0, terminate=False, node_id="node_clarify_1"),
                _single_node_plan(iteration=1, terminate=True, node_id="node_clarify_2"),
            ]
            executor = Executor(
                planner=_StaticPlanner(plans),
                node_runner=node_runner,
                artifact_store=artifact_store,
                observation_store=observation_store,
                policy=_make_policy(),
                event_sink=lambda e: events.append(e),
            )

            task = asyncio.create_task(executor.run(user_request="帮我做个实验", run_id="run_clarify"))

            # 等 Executor 到暂停点（发出 HitlRequestEvent）
            for _ in range(300):
                await asyncio.sleep(0.01)
                if any(isinstance(e, HitlRequestEvent) for e in events):
                    break
            else:
                task.cancel()
                pytest.fail("clarification pause never emitted HitlRequestEvent")

            # Executor 仍在等待
            assert not task.done()

            # 模拟用户答题
            executor.submit_clarification_response(
                {"answers": [{"question_header": "方向", "label": "图像"}]}
            )

            await asyncio.wait_for(task, timeout=5.0)

            # 验证 ClarificationResponse 产物落盘
            responses = [a for a in artifact_store.list_all() if a.artifact_type == "ClarificationResponse"]
            assert len(responses) == 1
            response = responses[0]
            assert response.payload["round_num"] == 1
            assert response.payload["answers"] == [{"question_header": "方向", "label": "图像"}]
            assert response.producer_role == RoleId.hitl
            # source_inputs 应指回产它的 ClarificationRequest
            assert len(response.source_inputs) == 1
            assert "ClarificationRequest" in response.source_inputs[0]

            # 最终应有 ClarifiedIntent（第二轮执行产出）
            clarified = [a for a in artifact_store.list_all() if a.artifact_type == "ClarifiedIntent"]
            assert len(clarified) == 1

        asyncio.run(run_case())


# ---------------------------------------------------------------------------
# AC3 —— 3 轮上限强制降级为 partial，携 cap 标识
# ---------------------------------------------------------------------------


@dataclass
class _AmbiguousLLMTools:
    """clarify_intent 技能 ctx.tools 的极简打桩：llm_chat 总返 ambiguous 的 JSON。"""

    response: str

    def with_permissions(self, permissions):
        del permissions
        return self

    def with_allowed_tools(self, allowed_tools):
        del allowed_tools
        return self

    async def llm_chat(self, messages, **kwargs):
        del messages, kwargs
        return self.response


def _make_response_artifact(*, round_num: int, artifact_id: str) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=artifact_id,
        artifact_type="ClarificationResponse",
        producer_role=RoleId.hitl,
        producer_skill="hitl",
        payload={
            "round_num": round_num,
            "answers": [{"question_header": f"q{round_num}", "label": f"a{round_num}"}],
        },
    )


def _make_ctx(
    *,
    user_request: str,
    tools: object,
    input_artifacts: list[ArtifactRecord],
) -> SkillContext:
    return SkillContext(
        skill_id="clarify_intent",
        role_id="conductor",
        run_id="run_cap",
        node_id="node_clarify_cap",
        goal=user_request,
        input_artifacts=input_artifacts,
        tools=tools,
        user_request=user_request,
    )


class TestRoundCap:
    def test_round_cap_forces_partial_with_cap_assumption(self) -> None:
        """LLM 在第 4 轮仍判 ambiguous 时，skill 强制降级 partial 并附 cap 标识。"""
        # LLM 一直想反问
        ambiguous_response = json.dumps(
            {
                "tier": "ambiguous",
                "inferred_goal": "",
                "inferred_fields": {"dataset": "MNIST"},
                "assumptions": [],
                "questions": [
                    {
                        "header": "方向",
                        "question": "哪个方向？",
                        "options": [
                            {"label": "A", "description": "A 方向"},
                            {"label": "B", "description": "B 方向"},
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )
        tools = _AmbiguousLLMTools(response=ambiguous_response)

        prior = [
            _make_response_artifact(round_num=1, artifact_id="resp_1"),
            _make_response_artifact(round_num=2, artifact_id="resp_2"),
            _make_response_artifact(round_num=3, artifact_id="resp_3"),
        ]
        # round_num = len(prior) + 1 = 4 > CLARIFY_ROUND_CAP (3) → 触发 cap
        ctx = _make_ctx(user_request="帮我做个实验", tools=tools, input_artifacts=prior)

        output = asyncio.run(clarify_run.run(ctx))

        assert output.success is True
        assert len(output.output_artifacts) == 1
        artifact = output.output_artifacts[0]
        # cap 后应是 ClarifiedIntent（partial），不再是 ClarificationRequest
        assert artifact.artifact_type == "ClarifiedIntent"
        assumptions = artifact.payload["assumptions"]
        cap_entries = [a for a in assumptions if a.get("field") == "__clarify_round_cap__"]
        assert len(cap_entries) == 1
        # 保留 LLM 给出的 inferred_fields
        assert artifact.payload["inferred_fields"] == {"dataset": "MNIST"}
        # inferred_goal 非空（LLM 空则用 fallback）
        assert artifact.payload["inferred_goal"]
        assert output.metadata["tier"] == "partial"

    def test_round_cap_does_not_trigger_before_round_4(self) -> None:
        """第 3 轮仍判 ambiguous 属正常行为，不触发 cap。"""
        ambiguous_response = json.dumps(
            {
                "tier": "ambiguous",
                "inferred_goal": "",
                "inferred_fields": {},
                "assumptions": [],
                "questions": [
                    {
                        "header": "方向",
                        "question": "哪个方向？",
                        "options": [
                            {"label": "A", "description": "A"},
                            {"label": "B", "description": "B"},
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )
        tools = _AmbiguousLLMTools(response=ambiguous_response)
        prior = [
            _make_response_artifact(round_num=1, artifact_id="resp_1"),
            _make_response_artifact(round_num=2, artifact_id="resp_2"),
        ]
        # round_num = 3 == CLARIFY_ROUND_CAP → 未过 cap
        ctx = _make_ctx(user_request="帮我做个实验", tools=tools, input_artifacts=prior)

        output = asyncio.run(clarify_run.run(ctx))

        assert output.success is True
        artifact = output.output_artifacts[0]
        assert artifact.artifact_type == "ClarificationRequest"
        assert artifact.payload["round_num"] == 3


# ---------------------------------------------------------------------------
# AC2 HTTP 端点：/api/runs/{run_id}/hitl artifact_type=ClarificationResponse 分支
# ---------------------------------------------------------------------------


class TestClarificationHttpEndpoint:
    """验证 runs 路由的 ClarificationResponse 分支会正确解包并分发给 runtime。"""

    def test_http_endpoint_dispatches_clarification_response(self) -> None:
        from fastapi.testclient import TestClient

        from app import app
        from src.server.routes import runs as runs_module

        run_id = "test_clarify_http_run"
        captured: dict[str, Any] = {}

        class _StubRuntime:
            def submit_clarification_response(self, payload: dict[str, Any]) -> None:
                captured["payload"] = payload

            def submit_hitl_response(self, text: str) -> None:  # 不应被调用
                captured["wrong_path"] = text

        stub = _StubRuntime()
        runs_module._ACTIVE_RUNTIMES[run_id] = stub  # type: ignore[assignment]
        try:
            client = TestClient(app)
            answers = [
                {"question_header": "方向", "label": "图像", "custom": None},
                {"question_header": "数据集", "label": "custom", "custom": "CIFAR-10"},
            ]
            resp = client.post(
                f"/api/runs/{run_id}/hitl",
                json={"artifact_type": "ClarificationResponse", "answers": answers},
            )

            assert resp.status_code == 200
            assert resp.json() == {"status": "accepted"}
            assert "wrong_path" not in captured
            assert captured["payload"] == {"answers": answers}
        finally:
            runs_module._ACTIVE_RUNTIMES.pop(run_id, None)

    def test_http_endpoint_rejects_non_list_answers(self) -> None:
        from fastapi.testclient import TestClient

        from app import app
        from src.server.routes import runs as runs_module

        run_id = "test_clarify_http_bad_run"

        class _StubRuntime:
            def submit_clarification_response(self, payload: dict[str, Any]) -> None:
                raise AssertionError("should not be called on validation failure")

            def submit_hitl_response(self, text: str) -> None:
                raise AssertionError("should not be called")

        runs_module._ACTIVE_RUNTIMES[run_id] = _StubRuntime()  # type: ignore[assignment]
        try:
            client = TestClient(app)
            resp = client.post(
                f"/api/runs/{run_id}/hitl",
                json={"artifact_type": "ClarificationResponse", "answers": "not-a-list"},
            )
            assert resp.status_code == 400
        finally:
            runs_module._ACTIVE_RUNTIMES.pop(run_id, None)
