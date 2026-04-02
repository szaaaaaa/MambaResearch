"""动态研究操作系统 — 规划器模块。

本模块是研究操作系统的「大脑」，负责将用户的研究请求转化为可执行的 DAG 执行计划。
核心职责包括：
- 调用 LLM 生成 RoutePlan（有向无环图），规划下一步需要执行的研究节点
- 为每个节点分配角色（conductor / researcher / analyst / writer / reviewer / experimenter）和技能
- 提供元技能函数（审查评估、终止判断、重规划触发）供 runtime 层调用

模块入口：
    Planner           — 规划器主类，调用 LLM 生成并校验 RoutePlan
    PlannerOutputError — LLM 输出无法解析或校验失败时抛出的异常
    assess_review_need — 根据不确定性/冲突/关键交付物等条件判断是否需要人工审查
    decide_termination — 根据已产出的 artifact 判断研究任务是否已完成
    replan_from_observation — 根据节点执行观测结果判断是否需要重新规划
"""

from src.dynamic_os.planner.meta_skills import assess_review_need, decide_termination, replan_from_observation
from src.dynamic_os.planner.planner import Planner, PlannerOutputError

__all__ = [
    "Planner",
    "PlannerOutputError",
    "assess_review_need",
    "decide_termination",
    "replan_from_observation",
]

