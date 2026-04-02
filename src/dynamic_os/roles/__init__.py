"""角色注册表包 —— Dynamic Research OS 的角色管理入口。

本包负责管理系统中所有角色（conductor、researcher、experimenter、
analyst、writer、reviewer、hitl）的定义和注册。

角色是 Dynamic OS 执行流水线中的核心概念：每个计划节点（PlanNode）
绑定一个角色，角色决定了该节点能调用哪些技能、接受哪些输入产物、
产出哪些输出产物，以及 LLM 的系统提示词内容。

角色定义存储在同目录的 roles.yaml 中，由 RoleRegistry 负责加载、
校验和查询。外部模块通过本包导入 RoleRegistry 即可使用角色系统。

典型用法::

    from src.dynamic_os.roles import RoleRegistry

    registry = RoleRegistry.from_file()
    spec = registry.get("researcher")
"""

from src.dynamic_os.roles.registry import RoleRegistry

# 公开接口：仅暴露 RoleRegistry 类
__all__ = ["RoleRegistry"]

