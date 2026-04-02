"""角色规格模块 —— 定义系统中各角色的能力和约束。

角色是 Dynamic OS 的执行主体抽象。每个 PlanNode 绑定一个角色，
角色决定了该节点的系统提示词、可用技能、输入输出产物类型等。

角色配置来自 roles/roles.yaml，解析后存储为 RoleSpec 实例。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.dynamic_os.contracts.route_plan import RoleId


class RoleSpec(BaseModel):
    """角色规格 —— 单个角色的完整配置。

    角色注册表（RoleRegistry）加载 roles.yaml 后，为每个角色
    创建一个 RoleSpec 实例。Executor 执行节点时根据角色 ID
    查找对应的 RoleSpec 来配置 LLM 调用参数。
    """

    model_config = {"frozen": True}

    # 角色唯一标识（对应 RoleId 枚举）
    id: RoleId
    # 角色功能描述
    description: str
    # LLM 系统提示词，定义角色的行为方式和专业领域
    system_prompt: str
    # 该角色默认允许使用的技能 ID 列表
    default_allowed_skills: list[str] = Field(default_factory=list)
    # 该角色可以接收的输入产物类型
    input_artifact_types: list[str] = Field(default_factory=list)
    # 该角色可以产出的输出产物类型
    output_artifact_types: list[str] = Field(default_factory=list)
    # 节点失败时的最大重试次数（0~5）
    max_retries: int = Field(2, ge=0, le=5)
    # 该角色被禁止执行的操作列表
    forbidden: list[str] = Field(default_factory=list)
