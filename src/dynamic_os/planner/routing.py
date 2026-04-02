"""角色路由 — 基于 artifact 类型判断角色是否可被激活。

本模块定义了每个角色（role）与其可接受的输入 artifact 类型之间的映射关系，
用于在规划阶段辅助判断：给定当前已有的 artifact 集合，哪些角色可以被有效激活。

注意：这些映射仅作为软约束（信息提示），不会硬性阻止 LLM 选择某个角色。
conductor 和 researcher 不在此映射中，因为它们在任何阶段都可以被激活。
"""

from __future__ import annotations

from typing import Iterable


# 各角色可激活的输入 artifact 类型映射表
# 键：角色 ID（与 RoleId 枚举值对应）
# 值：该角色期望接收的 artifact 类型元组
# 未在此表中出现的角色（如 conductor、researcher）视为无前置条件，始终可激活
ROLE_ACTIVATION_INPUTS: dict[str, tuple[str, ...]] = {
    "experimenter": ("SearchPlan", "EvidenceMap", "GapMap", "ExperimentPlan", "ExperimentIteration"),
    "analyst": ("ExperimentResults", "PaperNotes", "SourceSet", "EvidenceMap"),
    "writer": ("EvidenceMap", "ExperimentAnalysis", "PerformanceMetrics", "ReviewVerdict", "TrendAnalysis", "MethodComparison"),
    "reviewer": ("SourceSet", "ExperimentPlan", "ResearchReport"),
}


def activation_inputs_for_role(role_id: str) -> tuple[str, ...]:
    """获取指定角色的可激活输入 artifact 类型。

    参数
    ----------
    role_id : str
        角色标识符。

    返回
    -------
    tuple[str, ...]
        该角色可接受的 artifact 类型元组。未注册的角色返回空元组。
    """
    return ROLE_ACTIVATION_INPUTS.get(role_id, ())


def role_can_activate_from_inputs(role_id: str, input_types: Iterable[str]) -> bool:
    """判断给定角色在当前输入 artifact 类型集合下是否可以被激活。

    激活规则：
    - 如果角色未在 ROLE_ACTIVATION_INPUTS 中注册（无前置条件），始终返回 True
    - 否则，只要 input_types 与角色的可激活类型有交集，即可激活

    参数
    ----------
    role_id : str
        角色标识符。
    input_types : Iterable[str]
        当前可用的 artifact 类型集合。

    返回
    -------
    bool
        True 表示该角色可以被激活。
    """
    required_types = activation_inputs_for_role(role_id)
    if not required_types:
        # 无前置条件的角色始终可激活
        return True
    # 存在交集即可激活
    return bool(set(required_types) & set(input_types))
