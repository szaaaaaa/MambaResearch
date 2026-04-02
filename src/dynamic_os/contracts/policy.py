"""策略模块 —— 定义运行时的资源预算和安全权限约束。

策略是 Dynamic OS 的安全边界，由策略引擎（policy/engine.py）在运行时强制执行。
- BudgetPolicy 控制资源消耗上限（防止无限循环、过度消耗）
- PermissionPolicy 控制技能可以访问哪些系统能力（防止越权操作）

所有技能调用和工具调用都必须通过策略检查才能执行。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BudgetPolicy(BaseModel):
    """资源预算策略 —— 限制单次运行的资源消耗上限。

    防止研究任务因为 replan 循环或工具滥用而无限制地消耗资源。
    Runtime 在每次操作前检查剩余预算，超限时终止运行。
    """

    model_config = {"frozen": True}

    # 最大规划迭代次数（防止 replan 死循环）
    max_planning_iterations: int = Field(10, ge=1)
    # 最大节点执行次数（包含重试）
    max_node_executions: int = Field(30, ge=1)
    # 最大工具调用次数
    max_tool_invocations: int = Field(200, ge=1)
    # 最大运行墙钟时间（秒），默认 10 分钟
    max_wall_time_sec: float = Field(600.0, ge=30.0)
    # 最大 token 消耗量（LLM 调用累计）
    max_tokens: int = Field(500_000, ge=10_000)


class PermissionPolicy(BaseModel):
    """权限策略 —— 控制技能和工具可以访问哪些系统能力。

    策略引擎在工具调用前检查权限，不满足条件时拒绝执行并生成 PolicyBlockEvent。
    """

    model_config = {"frozen": True}

    # 是否允许网络访问（如 HTTP 请求、API 调用）
    allow_network: bool = True
    # 是否允许读取文件系统
    allow_filesystem_read: bool = True
    # 是否允许写入文件系统
    allow_filesystem_write: bool = True
    # 是否允许沙箱代码执行
    allow_sandbox_exec: bool = True
    # 是否允许远程代码执行（默认禁止，高风险操作）
    allow_remote_exec: bool = False
    # 允许访问的工作区路径列表
    approved_workspaces: list[str] = Field(default_factory=list)
    # 被禁止的危险命令列表
    blocked_commands: list[str] = Field(
        default_factory=lambda: [
            "rm -rf",
            "sudo",
            "su",
            "mkfs",
            "Remove-Item -Recurse -Force",
            "git reset --hard",
            "git checkout .",
        ]
    )
    # 被禁止访问的路径模式（glob 格式），保护敏感文件
    blocked_path_patterns: list[str] = Field(
        default_factory=lambda: [
            "**/.env",
            "**/credentials*",
            "**/secrets*",
        ]
    )

