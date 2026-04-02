"""策略引擎包 —— Dynamic Research OS 的运行时策略执行层。

本包提供预算控制和权限管理功能，在运行时对技能执行、工具调用、
文件访问等操作进行策略校验，防止资源滥用和越权操作。

主要导出：
- PolicyEngine：策略引擎核心类，负责预算追踪与权限断言
- PolicyViolationError：权限违规时抛出的异常
- BudgetExceededError：预算超限时抛出的异常（PolicyViolationError 的子类）
"""

from src.dynamic_os.policy.engine import BudgetExceededError, PolicyEngine, PolicyViolationError

__all__ = [
    "BudgetExceededError",
    "PolicyEngine",
    "PolicyViolationError",
]
