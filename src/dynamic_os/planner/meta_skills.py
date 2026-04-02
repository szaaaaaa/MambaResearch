"""规划器元技能 — 提供规划层面的轻量级决策函数。

本模块实现三个「元技能」函数，供 runtime 和规划器在每轮迭代中调用，
用于判断：
1. 当前节点输出是否需要人工审查（assess_review_need）
2. 某个节点的执行观测是否触发重规划（replan_from_observation）
3. 整体研究任务是否已达到终止条件（decide_termination）

这些函数不涉及 LLM 调用，是纯规则驱动的确定性逻辑。
"""

from __future__ import annotations

from src.dynamic_os.contracts.observation import NodeStatus, Observation


def assess_review_need(
    *,
    uncertainty_high: bool = False,
    evidence_conflicts: bool = False,
    critical_deliverable: bool = False,
    execution_blocked: bool = False,
) -> bool:
    """评估当前节点是否需要人工审查（human-in-the-loop review）。

    任一条件为 True 即触发审查。这是一个保守策略：宁可多审查，
    也不让高不确定性或有冲突的结果直接流入下游。

    参数
    ----------
    uncertainty_high : bool
        模型输出的不确定性是否较高。
    evidence_conflicts : bool
        多来源证据之间是否存在矛盾。
    critical_deliverable : bool
        当前节点是否即将产出关键交付物（如最终报告）。
    execution_blocked : bool
        执行是否因缺少信息或权限而被阻塞。

    返回
    -------
    bool
        True 表示需要人工审查。
    """
    return uncertainty_high or evidence_conflicts or critical_deliverable or execution_blocked


def replan_from_observation(observation: Observation | None) -> bool:
    """根据节点执行观测判断是否需要触发重规划。

    当节点执行结果为 partial（部分完成）、failed（失败）、
    或 needs_replan（显式请求重规划）时，返回 True，
    通知 runtime 重新调用 Planner 生成新的执行计划。

    参数
    ----------
    observation : Observation | None
        节点执行后产生的观测记录。为 None 表示节点尚未执行。

    返回
    -------
    bool
        True 表示需要重新规划。
    """
    if observation is None:
        return False
    return observation.status in {
        NodeStatus.partial,
        NodeStatus.failed,
        NodeStatus.needs_replan,
    }


def decide_termination(artifact_summaries: list[dict[str, str]]) -> bool:
    """判断研究任务是否已达到终止条件。

    当已产出的 artifact 中包含 ResearchReport 或 ReviewVerdict 时，
    认为研究任务的核心目标已经完成，可以终止执行循环。

    参数
    ----------
    artifact_summaries : list[dict[str, str]]
        所有已产出 artifact 的摘要列表，每项至少包含 "artifact_type" 字段。

    返回
    -------
    bool
        True 表示研究任务可以终止。
    """
    # 这两种 artifact 代表研究流程的最终产物
    final_artifact_types = {"ResearchReport", "ReviewVerdict"}
    return any(artifact.get("artifact_type") in final_artifact_types for artifact in artifact_summaries)

