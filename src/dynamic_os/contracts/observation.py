"""观测结果模块 —— 节点执行后的状态报告。

每个节点执行完毕后，Runtime 生成一个 Observation（观测），记录：
- 执行状态（成功/失败/部分完成等）
- 错误类型和详情
- 尝试过的方法和建议的后续操作

Planner 根据 Observation 决定是否需要重新规划（replan）。
这是 Runtime 与 Planner 之间的反馈通道。
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from src.dynamic_os.contracts.route_plan import RoleId


class NodeStatus(str, Enum):
    """节点执行状态枚举。

    - success: 完全成功，达成所有目标
    - partial: 部分成功，产出了一些结果但未完全达标
    - failed: 执行失败
    - needs_replan: 需要 Planner 重新规划
    - skipped: 被跳过（根据 FailurePolicy.skip 策略）
    """

    success = "success"
    partial = "partial"
    failed = "failed"
    needs_replan = "needs_replan"
    skipped = "skipped"


class ErrorType(str, Enum):
    """错误类型枚举 —— 对失败原因的分类标记。

    - tool_failure: 外部工具调用失败（如 API 超时、返回错误）
    - skill_error: 技能内部逻辑错误
    - timeout: 执行超时
    - policy_block: 被策略引擎拦截（如权限不足、预算用尽）
    - input_missing: 缺少必要的输入产物
    - llm_error: LLM 调用失败或输出无法解析
    - none: 无错误
    """

    tool_failure = "tool_failure"
    skill_error = "skill_error"
    timeout = "timeout"
    policy_block = "policy_block"
    input_missing = "input_missing"
    llm_error = "llm_error"
    none = "none"


class Observation(BaseModel):
    """观测结果 —— 节点执行后的完整状态报告。

    不可变模型。Planner 读取观测结果来评估当前进度，
    决定是否需要 replan、跳过还是终止运行。
    """

    model_config = {"frozen": True}

    # 产生该观测的节点 ID
    node_id: str
    # 执行角色（可以是具体角色或 "planner" 用于规划阶段观测）
    role: RoleId | Literal["planner"]
    # 节点执行状态
    status: NodeStatus
    # 错误类型分类
    error_type: ErrorType = ErrorType.none
    # 发生了什么的文字描述
    what_happened: str = ""
    # 已经尝试过的方法列表
    what_was_tried: list[str] = Field(default_factory=list)
    # 建议的后续可选方案
    suggested_options: list[str] = Field(default_factory=list)
    # 推荐的下一步操作
    recommended_action: str = ""
    # 该节点产出的产物引用列表
    produced_artifacts: list[str] = Field(
        default_factory=list,
        description="Artifact references in the form 'artifact:<type>:<id>'.",
    )
    # 结果置信度（0.0 ~ 1.0），用于 Planner 判断是否需要补充验证
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    # 节点执行耗时（毫秒）
    duration_ms: float = 0.0
