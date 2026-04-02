"""事件模块 —— 系统运行时产生的各类事件定义。

事件是 Dynamic OS 的实时通信机制。Runtime 在执行过程中发布事件，
前端通过 SSE（Server-Sent Events）接收并展示给用户。
事件也用于日志记录和运行状态回放。

所有事件继承自 BaseEvent，包含时间戳（ts）、运行 ID（run_id）和事件类型（type）。
事件按发生顺序组成一条完整的运行时间线。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class BaseEvent(BaseModel):
    """事件基类 —— 所有事件的公共字段。"""

    model_config = {"frozen": True}

    # 事件时间戳（ISO 格式）
    ts: str
    # 所属运行的唯一标识
    run_id: str
    # 事件类型标识符
    type: str


class PlanUpdateEvent(BaseEvent):
    """计划更新事件 —— Planner 生成或更新了执行计划时触发。"""

    type: Literal["plan_update"] = "plan_update"
    # 当前规划迭代次数
    planning_iteration: int
    # 完整的计划内容（序列化的 RoutePlan）
    plan: dict[str, Any]


class NodeStatusEvent(BaseEvent):
    """节点状态变更事件 —— 节点开始执行、完成或失败时触发。"""

    type: Literal["node_status"] = "node_status"
    # 触发事件的节点 ID
    node_id: str
    # 执行角色
    role: str
    # 节点状态（对应 NodeStatus 枚举值）
    status: str


class SkillInvokeEvent(BaseEvent):
    """技能调用事件 —— 技能开始执行或执行完毕时触发。"""

    type: Literal["skill_invoke"] = "skill_invoke"
    # 所在节点 ID
    node_id: str
    # 被调用的技能 ID
    skill_id: str
    # 执行阶段（如 "start"、"end"）
    phase: str


class ToolInvokeEvent(BaseEvent):
    """工具调用事件 —— 技能通过工具网关调用外部工具时触发。"""

    type: Literal["tool_invoke"] = "tool_invoke"
    # 所在节点 ID
    node_id: str
    # 发起调用的技能 ID
    skill_id: str
    # 被调用的工具 ID（格式：mcp.{server_id}.{tool_name}）
    tool_id: str
    # 执行阶段（如 "start"、"end"）
    phase: str


class ObservationEvent(BaseEvent):
    """观测事件 —— 节点执行完毕后发布的观测结果。"""

    type: Literal["observation"] = "observation"
    # 序列化的 Observation 内容
    observation: dict[str, Any]


class ReplanEvent(BaseEvent):
    """重新规划事件 —— 触发 replan 时发布。"""

    type: Literal["replan"] = "replan"
    # 触发重新规划的原因
    reason: str
    # 重新规划前的迭代次数
    previous_iteration: int
    # 重新规划后的迭代次数
    new_iteration: int


class ArtifactEvent(BaseEvent):
    """产物创建事件 —— 新产物被生产时触发。"""

    type: Literal["artifact_created"] = "artifact_created"
    # 产物唯一标识
    artifact_id: str
    # 产物类型
    artifact_type: str
    # 生产者角色
    producer_role: str
    # 生产者技能
    producer_skill: str


class PolicyBlockEvent(BaseEvent):
    """策略拦截事件 —— 操作被策略引擎拦截时触发。"""

    type: Literal["policy_block"] = "policy_block"
    # 被拦截的操作描述
    blocked_action: str
    # 拦截原因
    reason: str


class RunTerminateEvent(BaseEvent):
    """运行终止事件 —— 整个运行结束时触发。"""

    type: Literal["run_terminate"] = "run_terminate"
    # 终止原因
    reason: str
    # 最终产出的产物 ID 列表
    final_artifacts: list[str]


class HitlRequestEvent(BaseEvent):
    """人机交互请求事件 —— 系统需要用户决策时触发。"""

    type: Literal["hitl_request"] = "hitl_request"
    # 发起请求的节点 ID
    node_id: str
    # 向用户提出的问题
    question: str
    # 问题的背景上下文
    context: str


class HitlResponseEvent(BaseEvent):
    """人机交互响应事件 —— 用户回复决策后触发。"""

    type: Literal["hitl_response"] = "hitl_response"
    # 对应的节点 ID
    node_id: str
    # 用户的回复内容
    response: str

