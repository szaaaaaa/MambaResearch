from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from pydantic import BaseModel, Field, model_validator

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId


ROLE_ACTIVATION_INPUTS: dict[str, tuple[str, ...]] = {
    "experimenter": ("SearchPlan", "EvidenceMap", "GapMap", "ExperimentPlan"),
    "analyst": ("ExperimentResults",),
    "writer": ("EvidenceMap", "ExperimentAnalysis", "PerformanceMetrics"),
    "reviewer": ("SourceSet", "ExperimentPlan", "ResearchReport"),
}

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "research": (
        "research",
        "paper",
        "papers",
        "literature",
        "search",
        "retrieve",
        "evidence",
        "investigate",
        "study",
        "研究",
        "调研",
        "论文",
        "文献",
        "检索",
        "资料",
        "证据",
        "查找",
    ),
    "experiment": (
        "experiment",
        "benchmark",
        "ablation",
        "evaluate",
        "evaluation",
        "run code",
        "metric",
        "metrics",
        "latency",
        "accuracy",
        "实验",
        "评测",
        "基准",
        "消融",
        "指标",
        "准确率",
        "延迟",
        "运行代码",
        "运行",
    ),
    "analysis": (
        "analysis",
        "analyze",
        "compare",
        "comparison",
        "interpret",
        "analy",
        "分析",
        "对比",
        "比较",
        "解读",
        "归纳",
    ),
    "write": (
        "write",
        "draft",
        "report",
        "writeup",
        "summary",
        "synthesize",
        "article",
        "报告",
        "总结",
        "综述",
        "撰写",
        "写作",
        "输出",
        "结论",
        "闭环",
    ),
    "review": (
        "review",
        "critique",
        "audit",
        "revise",
        "qa",
        "check",
        "审核",
        "评审",
        "审阅",
        "复核",
        "检查",
        "复查",
        "批判",
        "质检",
    ),
}


@dataclass(frozen=True)
class RoleRoutingPolicy:
    selected_roles: tuple[str, ...] = ()
    required_roles: tuple[str, ...] = ()
    preferred_roles: tuple[str, ...] = ()
    activation_inputs: dict[str, tuple[str, ...]] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    intents: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "intents": list(self.intents),
            "selected_roles": list(self.selected_roles),
            "required_roles": list(self.required_roles),
            "preferred_roles": list(self.preferred_roles),
            "activation_inputs": {role_id: list(types) for role_id, types in self.activation_inputs.items()},
            "reasons": list(self.reasons),
        }


class RoleRoutingDecision(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    selected_roles: list[RoleId] = Field(..., min_length=1, max_length=4)
    required_roles: list[RoleId] = Field(default_factory=list, max_length=4)
    reasons: list[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def validate_roles(self) -> "RoleRoutingDecision":
        selected = [role.value for role in self.selected_roles]
        required = [role.value for role in self.required_roles]
        if len(set(selected)) != len(selected):
            raise ValueError("selected_roles must be unique")
        if len(set(required)) != len(required):
            raise ValueError("required_roles must be unique")
        missing = [role_id for role_id in required if role_id not in selected]
        if missing:
            raise ValueError(f"required_roles must be a subset of selected_roles: {', '.join(missing)}")
        return self


def derive_role_routing_policy(*, user_request: str, artifacts: list[ArtifactRecord]) -> RoleRoutingPolicy:
    artifact_types = {record.artifact_type for record in artifacts}
    intents = _detect_intents(user_request)
    required_roles: list[str] = []
    preferred_roles: list[str] = []
    reasons: list[str] = []

    has_planning = bool({"TopicBrief", "SearchPlan"} & artifact_types)
    has_research_material = bool({"SourceSet", "PaperNotes", "EvidenceMap", "GapMap"} & artifact_types)
    has_experiment_context = bool({"SearchPlan", "EvidenceMap", "GapMap", "ExperimentPlan"} & artifact_types)
    has_experiment_results = "ExperimentResults" in artifact_types
    has_writer_context = bool({"EvidenceMap", "ExperimentAnalysis", "PerformanceMetrics"} & artifact_types)
    has_review_context = bool({"SourceSet", "ExperimentPlan", "ResearchReport"} & artifact_types)

    if not artifact_types:
        _append_unique(preferred_roles, "conductor")
        reasons.append("当前还没有任何 artifact，通常应先由 conductor 规划下一段 DAG。")

    if "research" in intents:
        if not has_planning:
            if not (has_experiment_context or has_writer_context or has_review_context):
                _append_unique(required_roles, "conductor")
                reasons.append("研究类请求缺少 TopicBrief/SearchPlan，必须先启用 conductor 做规划。")
        elif not has_research_material:
            _append_unique(required_roles, "researcher")
            reasons.append("已有规划但还没有资料或证据，下一步应启用 researcher。")
        else:
            _append_unique(preferred_roles, "researcher")

    if "experiment" in intents:
        if has_experiment_results:
            _append_unique(preferred_roles, "analyst")
            reasons.append("已经有 ExperimentResults，实验型请求更适合交给 analyst 解读。")
        elif has_experiment_context:
            _append_unique(required_roles, "experimenter")
            reasons.append("已有实验上下文，实验型请求应启用 experimenter。")
        else:
            _append_unique(preferred_roles, "conductor")
            reasons.append("实验型请求缺少实验上下文，先让 conductor 规划更稳妥。")

    if "analysis" in intents:
        if has_experiment_results:
            _append_unique(required_roles, "analyst")
            reasons.append("分析型请求且已有 ExperimentResults，应启用 analyst。")
        elif has_experiment_context:
            _append_unique(preferred_roles, "experimenter")
            reasons.append("分析型请求缺少结果，先由 experimenter 产出结果更合理。")

    if "write" in intents:
        if "review" in intents and "ResearchReport" in artifact_types:
            pass
        elif has_writer_context:
            _append_unique(required_roles, "writer")
            reasons.append("写作型请求且已有证据/分析产物，应启用 writer。")
        elif has_experiment_results:
            _append_unique(preferred_roles, "analyst")
            reasons.append("写作前已有实验结果但缺少分析，优先 analyst。")
        elif not has_planning:
            _append_unique(preferred_roles, "conductor")
            reasons.append("写作型请求缺少上游规划或证据，先让 conductor 组织流程。")

    if "review" in intents:
        if has_review_context:
            _append_unique(required_roles, "reviewer")
            reasons.append("评审型请求且已有可评审产物，应启用 reviewer。")
        elif has_writer_context:
            _append_unique(preferred_roles, "writer")
            reasons.append("评审前还缺少最终可评审产物，通常先由 writer 产出。")
        elif not has_planning:
            _append_unique(preferred_roles, "conductor")
            reasons.append("评审型请求当前没有可评审产物，先由 conductor 组织上游步骤。")

    selected_roles = list(required_roles)
    for role_id in preferred_roles:
        _append_unique(selected_roles, role_id)
    if not selected_roles and not artifact_types:
        selected_roles = ["conductor"]
        reasons.append("默认回退到 conductor，避免无角色可选。")

    return RoleRoutingPolicy(
        selected_roles=tuple(selected_roles),
        required_roles=tuple(required_roles),
        preferred_roles=tuple(preferred_roles),
        activation_inputs={role_id: input_types for role_id, input_types in ROLE_ACTIVATION_INPUTS.items()},
        reasons=tuple(reasons),
        intents=tuple(sorted(intents)),
    )


def _detect_intents(user_request: str) -> set[str]:
    lowered = " ".join(user_request.lower().split())
    intents = {
        intent
        for intent, keywords in INTENT_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    }
    if not intents:
        intents.add("research")
    return intents


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def activation_inputs_for_role(role_id: str) -> tuple[str, ...]:
    return ROLE_ACTIVATION_INPUTS.get(role_id, ())


def role_can_activate_from_inputs(role_id: str, input_types: Iterable[str]) -> bool:
    required_types = activation_inputs_for_role(role_id)
    if not required_types:
        return True
    return bool(set(required_types) & set(input_types))


def merge_routing_policy(
    *,
    base_policy: RoleRoutingPolicy,
    decision: RoleRoutingDecision | None,
) -> RoleRoutingPolicy:
    if decision is None:
        return base_policy

    selected_roles = [role.value for role in decision.selected_roles]
    for role_id in base_policy.required_roles:
        _append_unique(selected_roles, role_id)

    required_roles = [role.value for role in decision.required_roles]
    for role_id in base_policy.required_roles:
        _append_unique(required_roles, role_id)

    preferred_roles = [role_id for role_id in selected_roles if role_id not in required_roles]
    reasons = list(base_policy.reasons)
    for reason in decision.reasons:
        if reason not in reasons:
            reasons.append(reason)

    return RoleRoutingPolicy(
        selected_roles=tuple(selected_roles),
        required_roles=tuple(required_roles),
        preferred_roles=tuple(preferred_roles),
        activation_inputs=base_policy.activation_inputs,
        reasons=tuple(reasons),
        intents=base_policy.intents,
    )
