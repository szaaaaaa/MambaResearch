"""执行器包 —— 负责按照路由计划（RoutePlan）驱动节点执行。

执行器是 Runtime 和技能之间的桥梁：
- Executor: 顶层执行循环，协调 Planner 和 NodeRunner，管理 replan 循环
- NodeRunner: 单节点执行器，负责技能选择、调用和观测生成

执行流程：Executor.run() → Planner.plan() → Executor.execute_plan()
→ NodeRunner.run_node() → Skill.run() → Observation → 下一轮或终止
"""

from src.dynamic_os.executor.executor import Executor, ExecutorRunResult, PlanExecutionResult
from src.dynamic_os.executor.node_runner import NodeExecutionResult, NodeRunner

__all__ = [
    "Executor",
    "ExecutorRunResult",
    "NodeExecutionResult",
    "NodeRunner",
    "PlanExecutionResult",
]
