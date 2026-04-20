"""clarify_intent 技能测试。

覆盖 Task 1（docs/plans/2026-04-20-clarify-intent.md）的 AC2–AC5：

- test_tier1_clear                — Tier 1: LLM 返 clear → ClarifiedIntent 且 assumptions==[]
- test_tier2_partial              — Tier 2: LLM 返 partial → ClarifiedIntent 且 assumptions 非空
- test_tier3_ambiguous            — Tier 3: LLM 返 ambiguous → ClarificationRequest 且 questions 合法
- test_multi_round_increments_num — 多轮 ClarificationResponse 累积 round_num
- test_smoke_real_llm             — integration marker，真实 LLM 烟雾测，默认跳过

全量 test runner 会因 pytest.ini 的 `-m "not integration"` 默认跳过 smoke。
手动启用：`pytest tests/skills/test_clarify_intent.py -m integration`。
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass

import pytest

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext
from src.dynamic_os.skills.builtins.clarify_intent import run as clarify_run


# ---------------------------------------------------------------------------
# 测试工具：FakeTools + _make_ctx
# ---------------------------------------------------------------------------


@dataclass
class _FakeTools:
    """替换 ctx.tools，返回预设的 LLM JSON 字符串。"""

    response_text: str
    captured: list[tuple[list, dict]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.captured = []

    def with_permissions(self, permissions):  # noqa: D401 — 协议占位
        del permissions
        return self

    def with_allowed_tools(self, allowed_tools):  # noqa: D401 — 协议占位
        del allowed_tools
        return self

    async def llm_chat(self, messages, **kwargs):
        self.captured.append((list(messages), dict(kwargs)))
        return self.response_text


def _make_ctx(
    user_request: str,
    *,
    tools: object,
    input_artifacts: list[ArtifactRecord] | None = None,
    node_id: str = "node_clarify_1",
    run_id: str = "run_clarify_1",
) -> SkillContext:
    return SkillContext(
        skill_id="clarify_intent",
        role_id="conductor",
        run_id=run_id,
        node_id=node_id,
        goal=user_request,
        input_artifacts=list(input_artifacts or []),
        tools=tools,
        user_request=user_request,
    )


def _make_response_artifact(
    *, round_num: int, answers: list[dict], artifact_id: str,
) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=artifact_id,
        artifact_type="ClarificationResponse",
        producer_role=RoleId.hitl,
        producer_skill="hitl",
        payload={"round_num": round_num, "answers": answers},
    )


# ---------------------------------------------------------------------------
# Tier 1 — clear
# ---------------------------------------------------------------------------


def test_tier1_clear() -> None:
    """LLM 判定 clear 时，skill 输出 ClarifiedIntent 且 assumptions 为空。"""
    fake_llm_json = json.dumps(
        {
            "tier": "clear",
            "inferred_goal": "在 MNIST 上训练一个两层 MLP 并报告测试集准确率。",
            "inferred_fields": {
                "dataset": "MNIST",
                "model": "2-layer MLP",
                "metric": "accuracy",
            },
            "assumptions": [],
            "questions": [],
        },
        ensure_ascii=False,
    )
    tools = _FakeTools(response_text=fake_llm_json)
    ctx = _make_ctx("在 MNIST 上用两层 MLP 跑出 accuracy", tools=tools)

    output = asyncio.run(clarify_run.run(ctx))

    assert output.success is True
    assert len(output.output_artifacts) == 1
    artifact = output.output_artifacts[0]
    assert artifact.artifact_type == "ClarifiedIntent"
    assert artifact.payload["assumptions"] == []
    assert artifact.payload["inferred_goal"].startswith("在 MNIST")
    assert output.metadata["tier"] == "clear"


# ---------------------------------------------------------------------------
# Tier 2 — partial
# ---------------------------------------------------------------------------


def test_tier2_partial() -> None:
    """LLM 判定 partial 时，assumptions 至少含一条 {field, value, reason}。"""
    fake_llm_json = json.dumps(
        {
            "tier": "partial",
            "inferred_goal": "在 MNIST 上训练一个 MLP 并报告 accuracy。",
            "inferred_fields": {"dataset": "MNIST", "metric": "accuracy"},
            "assumptions": [
                {
                    "field": "model",
                    "value": "2-layer MLP (128 hidden units)",
                    "reason": "用户未指定模型；选一个在 MNIST 上能快速收敛的最小基线。",
                },
                {
                    "field": "epochs",
                    "value": 5,
                    "reason": "用户未指定训练轮次；5 epochs 在 MNIST 上通常足够收敛。",
                },
            ],
            "questions": [],
        },
        ensure_ascii=False,
    )
    tools = _FakeTools(response_text=fake_llm_json)
    ctx = _make_ctx("在 MNIST 上跑一个实验", tools=tools)

    output = asyncio.run(clarify_run.run(ctx))

    assert output.success is True
    artifact = output.output_artifacts[0]
    assert artifact.artifact_type == "ClarifiedIntent"
    assumptions = artifact.payload["assumptions"]
    assert len(assumptions) >= 1
    first = assumptions[0]
    assert set(first.keys()) == {"field", "value", "reason"}
    assert first["field"] and first["reason"]
    assert output.metadata["tier"] == "partial"


# ---------------------------------------------------------------------------
# Tier 3 — ambiguous
# ---------------------------------------------------------------------------


def test_tier3_ambiguous() -> None:
    """LLM 判定 ambiguous 时，输出 ClarificationRequest 且 questions 合法。"""
    fake_llm_json = json.dumps(
        {
            "tier": "ambiguous",
            "inferred_goal": "",
            "inferred_fields": {},
            "assumptions": [],
            "questions": [
                {
                    "header": "实验方向",
                    "question": "你想做哪个方向的实验？",
                    "options": [
                        {"label": "图像分类", "description": "在标准数据集上训练分类模型。"},
                        {"label": "文本分类", "description": "在 NLP 数据集上训练文本分类模型。"},
                        {"label": "回归任务", "description": "在结构化数据上做数值预测。"},
                    ],
                },
                {
                    "header": "硬件偏好",
                    "question": "有没有硬件偏好？",
                    "options": [
                        {"label": "仅 CPU", "description": "跑在本地 CPU 上即可。"},
                        {"label": "需要 GPU", "description": "用有限 GPU 资源加速。"},
                    ],
                },
            ],
        },
        ensure_ascii=False,
    )
    tools = _FakeTools(response_text=fake_llm_json)
    ctx = _make_ctx("帮我做个实验", tools=tools)

    output = asyncio.run(clarify_run.run(ctx))

    assert output.success is True
    artifact = output.output_artifacts[0]
    assert artifact.artifact_type == "ClarificationRequest"
    assert artifact.payload["round_num"] == 1
    questions = artifact.payload["questions"]
    assert len(questions) >= 1
    for question in questions:
        assert set(question.keys()) == {"header", "question", "options"}
        assert len(question["header"]) <= 12
        assert question["question"]
        assert 2 <= len(question["options"]) <= 4
        for option in question["options"]:
            assert set(option.keys()) == {"label", "description"}
            assert option["label"] and option["description"]


# ---------------------------------------------------------------------------
# 多轮累积：input_artifacts 里的 ClarificationResponse 推高 round_num
# ---------------------------------------------------------------------------


def test_multi_round_increments_num() -> None:
    """有 N 条 ClarificationResponse → round_num = N + 1。"""
    fake_llm_json = json.dumps(
        {
            "tier": "ambiguous",
            "inferred_goal": "",
            "inferred_fields": {},
            "assumptions": [],
            "questions": [
                {
                    "header": "数据集",
                    "question": "用哪个数据集？",
                    "options": [
                        {"label": "MNIST", "description": "手写数字分类。"},
                        {"label": "CIFAR-10", "description": "10 类自然图像。"},
                    ],
                }
            ],
        },
        ensure_ascii=False,
    )
    tools = _FakeTools(response_text=fake_llm_json)
    prior = [
        _make_response_artifact(
            round_num=1,
            answers=[{"question_header": "实验方向", "label": "图像分类"}],
            artifact_id="resp_1",
        ),
        _make_response_artifact(
            round_num=2,
            answers=[{"question_header": "硬件偏好", "label": "仅 CPU"}],
            artifact_id="resp_2",
        ),
    ]
    ctx = _make_ctx("帮我做个实验", tools=tools, input_artifacts=prior)

    output = asyncio.run(clarify_run.run(ctx))

    assert output.success is True
    artifact = output.output_artifacts[0]
    assert artifact.artifact_type == "ClarificationRequest"
    assert artifact.payload["round_num"] == 3  # 2 prior + 1


# ---------------------------------------------------------------------------
# Smoke test —— 真 LLM，默认跳过
# ---------------------------------------------------------------------------


@dataclass
class _RealLLMTools:
    """最小化 real-LLM tools：直连 OpenAI chat.completions，跳过 MCP runtime。

    用途仅限 smoke test —— 验证 prompt + JSON schema + 解析管线的端到端行为，
    不验证 MCP 通道本身（MCP 集成另有自己的测试）。
    """

    model: str = "gpt-4o-mini"

    def with_permissions(self, permissions):  # noqa: D401
        del permissions
        return self

    def with_allowed_tools(self, allowed_tools):  # noqa: D401
        del allowed_tools
        return self

    async def llm_chat(self, messages, **kwargs):
        from openai import AsyncOpenAI

        client = AsyncOpenAI()
        # OpenAI 的 json_schema 模式要求 name + schema；若 skill 传了 response_format（JSON
        # schema 对象），这里包一层 name 使其符合 OpenAI 的入参形状。
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.2),
        }
        response_format = kwargs.get("response_format")
        if isinstance(response_format, dict):
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "clarify_intent",
                    "schema": response_format,
                    "strict": False,
                },
            }
        completion = await client.chat.completions.create(**payload)
        return completion.choices[0].message.content or ""


@pytest.mark.integration
def test_smoke_real_llm() -> None:
    """用真 OpenAI 跑一次模糊请求，断言产出合法的 artifact。

    手动启用：`pytest tests/skills/test_clarify_intent.py -m integration`。
    未配置 OPENAI_API_KEY 时跳过。
    """
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")

    ctx = _make_ctx("帮我做个实验", tools=_RealLLMTools())
    output = asyncio.run(clarify_run.run(ctx))

    assert output.success is True, output.error
    assert len(output.output_artifacts) == 1
    artifact = output.output_artifacts[0]
    # 对"帮我做个实验"这种极模糊输入，真实模型大概率选 ambiguous；
    # 放宽断言允许 partial/clear（视模型而定），但产物类型必须是这两种之一。
    assert artifact.artifact_type in ("ClarificationRequest", "ClarifiedIntent")
    if artifact.artifact_type == "ClarificationRequest":
        assert len(artifact.payload["questions"]) >= 1
