"""技能注册表模块 — 管理所有已加载技能的中心索引。

本模块实现技能子系统的第三阶段：**注册**。
SkillRegistry 负责：
    1. 协调发现和加载流程，将结果汇总为一张 ID → LoadedSkill 的映射表
    2. 检测重复的技能 ID 并报错
    3. 提供按 ID 查询和列表接口
    4. 校验技能与角色的兼容性（双向检查）

在整个系统中，SkillRegistry 是技能信息的唯一权威来源。
执行器（executor）和规划器（planner）均通过它获取技能对象。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from src.dynamic_os.roles.registry import RoleRegistry
from src.dynamic_os.skills.discovery import discover_skill_packages
from src.dynamic_os.skills.loader import LoadedSkill, load_skill


class SkillRegistry:
    """技能注册表 — 存储和管理所有已加载技能的中心组件。

    注册表维护一个 ``skill_id -> LoadedSkill`` 的内部字典，
    支持刷新（重新扫描并加载）、按 ID 查询、列表遍历、以及角色兼容性校验。
    """

    def __init__(self, roots: list[str | Path] | None = None) -> None:
        """初始化注册表，设定技能搜索根目录。

        参数
        ----------
        roots : list[str | Path] | None, optional
            技能包的搜索根目录列表。若为 None，则默认搜索两个位置：
            - 内置技能目录：当前包下的 ``builtins/``
            - 项目自定义技能目录：工作目录下的 ``skills/``
        """
        package_dir = Path(__file__).resolve().parent
        # 默认搜索路径：内置技能目录 + 工作目录下的自定义技能目录
        self._roots = [Path(item) for item in (roots or [package_dir / "builtins", Path.cwd() / "skills"])]
        # 技能 ID 到 LoadedSkill 的映射表
        self._skills: dict[str, LoadedSkill] = {}

    @property
    def roots(self) -> list[Path]:
        """返回当前配置的搜索根目录列表（副本）。"""
        return list(self._roots)

    def refresh(self) -> None:
        """重新扫描所有根目录，发现并加载技能包，更新内部映射表。

        此方法会完全替换已有的技能映射。若发现重复的技能 ID，
        将抛出 ValueError 而不进行部分更新。

        异常
        ------
        ValueError
            当多个技能包声明了相同的 ID 时抛出。
        """
        # 发现 → 加载 全部技能
        loaded = [load_skill(package) for package in discover_skill_packages(self._roots)]
        # 检测重复 ID：同一 ID 出现多次说明存在命名冲突
        duplicates = [skill_id for skill_id, count in Counter(skill.spec.id for skill in loaded).items() if count > 1]
        if duplicates:
            raise ValueError(f"duplicate skill ids found: {', '.join(sorted(duplicates))}")
        # 替换内部映射
        self._skills = {skill.spec.id: skill for skill in loaded}

    @classmethod
    def discover(cls, roots: list[str | Path] | None = None) -> "SkillRegistry":
        """便捷工厂方法：创建注册表并立即执行一次发现与加载。

        参数
        ----------
        roots : list[str | Path] | None, optional
            搜索根目录列表，含义同 ``__init__``。

        返回
        -------
        SkillRegistry
            已填充技能数据的注册表实例。
        """
        registry = cls(roots)
        registry.refresh()
        return registry

    def get(self, skill_id: str) -> LoadedSkill:
        """按 ID 获取已加载的技能。

        参数
        ----------
        skill_id : str
            技能的唯一标识符（即技能包的目录名）。

        返回
        -------
        LoadedSkill
            对应的已加载技能对象。

        异常
        ------
        KeyError
            当指定 ID 的技能不存在时抛出。
        """
        return self._skills[skill_id]

    def list(self) -> list[LoadedSkill]:
        """返回所有已加载技能的列表，按 ID 字母序排序。"""
        return [self._skills[skill_id] for skill_id in sorted(self._skills)]

    def validate_role_assignment(
        self,
        role_id: str,
        skill_ids: list[str],
        role_registry: RoleRegistry,
    ) -> None:
        """校验一组技能是否可以合法分配给指定角色。

        执行两层校验：
            1. **技能存在性** — 所有 skill_ids 必须在注册表中已注册
            2. **角色白名单** — 通过 RoleRegistry 检查角色是否允许使用这些技能
            3. **技能适用角色** — 反向检查每个技能的 applicable_roles 是否包含该角色

        参数
        ----------
        role_id : str
            要分配技能的角色 ID。
        skill_ids : list[str]
            要分配的技能 ID 列表。
        role_registry : RoleRegistry
            角色注册表，用于获取角色定义和校验白名单。

        异常
        ------
        ValueError
            当存在未知技能 ID 或角色与技能不兼容时抛出。
        """
        role = role_registry.get(role_id)
        # 检查是否存在未注册的技能 ID
        missing = [skill_id for skill_id in skill_ids if skill_id not in self._skills]
        if missing:
            raise ValueError(f"unknown skills for role {role.id.value}: {', '.join(missing)}")
        # 通过角色注册表校验角色的技能白名单
        role_registry.validate_skill_allowlist(role.id, skill_ids)
        # 反向检查：技能自身声明的 applicable_roles 是否包含该角色
        incompatible = [
            skill_id
            for skill_id in skill_ids
            if role.id not in self.get(skill_id).spec.applicable_roles
        ]
        if incompatible:
            raise ValueError(f"role {role.id.value} is not applicable for skills: {', '.join(incompatible)}")
