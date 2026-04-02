"""Dynamic Research OS 合约层统一导出模块。

合约层（contracts）是整个 Dynamic OS 的类型基础，定义了系统中所有核心数据结构。
其他模块（planner、executor、runtime 等）都依赖这些合约进行通信。

主要包含以下子模块：
- route_plan: 路由计划（DAG 执行图）的数据结构
- artifact: 产物记录，技能执行产出的结构化数据
- skill_io: 技能的输入上下文和输出结果
- skill_spec: 技能规格声明（权限、超时、输入输出契约）
- observation: 节点执行后的观测结果
- events: 系统运行时产生的各类事件
- policy: 预算策略和权限策略
- role_spec: 角色规格定义
"""

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.events import (
    ArtifactEvent,
    BaseEvent,
    NodeStatusEvent,
    ObservationEvent,
    PlanUpdateEvent,
    PolicyBlockEvent,
    ReplanEvent,
    RunTerminateEvent,
    SkillInvokeEvent,
    ToolInvokeEvent,
)
from src.dynamic_os.contracts.observation import ErrorType, NodeStatus, Observation
from src.dynamic_os.contracts.policy import BudgetPolicy, PermissionPolicy
from src.dynamic_os.contracts.role_spec import RoleSpec
from src.dynamic_os.contracts.route_plan import (
    EdgeCondition,
    FailurePolicy,
    PlanEdge,
    PlanNode,
    RoleId,
    RoutePlan,
)
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput
from src.dynamic_os.contracts.skill_spec import SkillInputContract, SkillPermissions, SkillSpec

__all__ = [
    "ArtifactEvent",
    "ArtifactRecord",
    "BaseEvent",
    "BudgetPolicy",
    "EdgeCondition",
    "ErrorType",
    "FailurePolicy",
    "NodeStatus",
    "NodeStatusEvent",
    "Observation",
    "ObservationEvent",
    "PermissionPolicy",
    "PlanEdge",
    "PlanNode",
    "PlanUpdateEvent",
    "PolicyBlockEvent",
    "ReplanEvent",
    "RoleId",
    "RoleSpec",
    "RoutePlan",
    "RunTerminateEvent",
    "SkillContext",
    "SkillInputContract",
    "SkillInvokeEvent",
    "SkillOutput",
    "SkillPermissions",
    "SkillSpec",
    "ToolInvokeEvent",
]
