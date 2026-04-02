"""角色注册表模块 —— 负责角色定义的加载、存储与校验。

本模块是 Dynamic Research OS 角色系统的核心实现。它从 roles.yaml
配置文件中加载所有角色定义，构建为内存中的注册表，并提供以下能力：

1. **角色查询**：根据 RoleId 获取对应的 RoleSpec
2. **完整性校验**：确保 RoleId 枚举中的每个角色都有对应的配置
3. **技能白名单校验**：验证计划节点分配的技能是否在角色允许范围内
4. **路由计划校验**：批量验证整个执行计划中所有节点的技能合法性
5. **自定义技能扩展**：支持从项目工作目录加载用户自定义的技能扩展配置

在系统启动时，Runtime 通过 ``RoleRegistry.from_file()`` 或
``RoleRegistry.from_file_with_custom()`` 创建注册表实例，后续的
Planner 和 Executor 都依赖该实例进行角色相关的查询和校验。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.dynamic_os.contracts.role_spec import RoleSpec
from src.dynamic_os.contracts.route_plan import RoleId, RoutePlan


class RoleRegistry:
    """角色注册表 —— 管理系统中所有角色定义的中心化容器。

    RoleRegistry 在初始化时接收一组 RoleSpec，构建以 RoleId 为键的
    查找字典，并立即验证：
    - 角色 ID 不能重复
    - RoleId 枚举中的每个成员都必须有对应的 RoleSpec

    这保证了系统运行时任何合法的 RoleId 都能找到对应配置，
    避免执行阶段出现 KeyError。

    属性
    ----------
    _roles : dict[RoleId, RoleSpec]
        以角色 ID 为键的角色规格字典，用于 O(1) 查找。
    """

    def __init__(self, roles: list[RoleSpec]) -> None:
        """初始化角色注册表。

        参数
        ----------
        roles : list[RoleSpec]
            角色规格列表，通常从 roles.yaml 解析得到。

        异常
        ------
        ValueError
            当存在重复的角色 ID，或 RoleId 枚举中有角色缺少配置时抛出。
        """
        # 构建 RoleId -> RoleSpec 的查找字典
        self._roles = {role.id: role for role in roles}
        # 检查是否有重复 ID（字典去重后长度不一致说明有重复）
        if len(self._roles) != len(roles):
            raise ValueError("role ids must be unique")

        # 检查 RoleId 枚举的每个成员是否都有对应配置
        missing = [role_id.value for role_id in RoleId if role_id not in self._roles]
        if missing:
            raise ValueError(f"missing role specs: {', '.join(missing)}")

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "RoleRegistry":
        """从 YAML 文件加载角色配置并创建注册表。

        参数
        ----------
        path : str | Path | None, optional
            角色配置文件路径。为 None 时默认使用同目录下的 roles.yaml。

        返回
        -------
        RoleRegistry
            加载完成的角色注册表实例。
        """
        # 未指定路径时，使用本文件同目录下的 roles.yaml
        role_path = Path(path) if path is not None else Path(__file__).with_name("roles.yaml")
        # 读取并解析 YAML 配置
        payload = yaml.safe_load(role_path.read_text(encoding="utf-8"))
        # 将每个字典项验证并转换为 RoleSpec 模型
        roles = [RoleSpec.model_validate(item) for item in payload]
        return cls(roles)

    @classmethod
    def from_file_with_custom(cls, cwd: str | Path, path: str | Path | None = None) -> "RoleRegistry":
        """加载角色配置，并合并项目工作目录中的自定义技能扩展。

        该方法在 from_file 的基础上，额外扫描项目工作目录中的自定义
        技能配置（通过 load_custom_skill_additions），将用户自定义的
        技能追加到对应角色的 default_allowed_skills 列表中。

        这允许用户在不修改系统 roles.yaml 的前提下，为角色扩展新技能。

        参数
        ----------
        cwd : str | Path
            项目工作目录路径，用于查找自定义技能配置文件。
        path : str | Path | None, optional
            角色配置文件路径，传递给 from_file。

        返回
        -------
        RoleRegistry
            合并了自定义技能扩展的角色注册表实例。
        """
        # 先加载基础角色配置
        registry = cls.from_file(path)
        # 延迟导入，避免循环依赖
        from src.dynamic_os.skills.custom_config import load_custom_skill_additions

        # 加载项目目录中的自定义技能扩展配置
        additions = load_custom_skill_additions(Path(cwd))
        if not additions:
            return registry
        # 遍历所有角色，合并自定义技能到白名单
        updated_roles: list[RoleSpec] = []
        for role in registry.list():
            extra_skills = additions.get(role.id.value, [])
            if extra_skills:
                # 将新技能追加到已有白名单，跳过重复项
                merged = list(role.default_allowed_skills) + [
                    s for s in extra_skills if s not in role.default_allowed_skills
                ]
                # 使用 model_copy 创建不可变模型的更新副本
                role = role.model_copy(update={"default_allowed_skills": merged})
            updated_roles.append(role)
        return cls(updated_roles)

    def get(self, role_id: RoleId | str) -> RoleSpec:
        """根据角色 ID 获取对应的角色规格。

        参数
        ----------
        role_id : RoleId | str
            角色标识符，可以是 RoleId 枚举值或其字符串形式。

        返回
        -------
        RoleSpec
            对应的角色规格实例。

        异常
        ------
        KeyError
            当角色 ID 不存在于注册表中时抛出。
        ValueError
            当字符串无法转换为有效的 RoleId 枚举值时抛出。
        """
        return self._roles[RoleId(role_id)]

    def list(self) -> list[RoleSpec]:
        """按 RoleId 枚举顺序返回所有角色规格。

        返回
        -------
        list[RoleSpec]
            所有已注册角色的规格列表，顺序与 RoleId 枚举定义一致。
        """
        return [self._roles[role_id] for role_id in RoleId]

    def validate_skill_allowlist(self, role_id: RoleId | str, skill_ids: list[str]) -> None:
        """验证一组技能 ID 是否都在指定角色的允许列表内。

        Planner 生成计划后、Executor 执行前，调用此方法确保
        节点分配的技能不超出角色权限范围。

        参数
        ----------
        role_id : RoleId | str
            要校验的角色标识符。
        skill_ids : list[str]
            待校验的技能 ID 列表。

        异常
        ------
        ValueError
            当存在不在角色白名单中的技能时抛出，错误信息包含所有违规技能名。
        """
        role = self.get(role_id)
        # 筛选出不在白名单中的技能
        disallowed = [skill_id for skill_id in skill_ids if skill_id not in role.default_allowed_skills]
        if disallowed:
            raise ValueError(f"role {role.id.value} cannot use skills: {', '.join(disallowed)}")

    def validate_route_plan(self, plan: RoutePlan) -> None:
        """校验整个路由计划中所有节点的技能分配合法性。

        遍历计划中的每个节点，检查其分配的技能是否在对应角色的
        白名单范围内。hitl（人工介入）节点跳过校验，因为其技能
        由系统固定分配。

        参数
        ----------
        plan : RoutePlan
            待校验的路由计划。

        异常
        ------
        ValueError
            当任意节点的技能分配超出角色允许范围时抛出。
        """
        for node in plan.nodes:
            # hitl 节点由系统控制，跳过技能白名单校验
            if node.role == RoleId.hitl:
                continue
            self.validate_skill_allowlist(node.role, node.allowed_skills)
