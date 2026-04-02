"""技能加载模块 — 将已发现的技能包解析为可执行的技能对象。

本模块实现技能子系统的第二阶段：**加载**。
给定一个已发现的技能包（DiscoveredSkill），本模块完成以下工作：
    1. 解析 ``skill.yaml`` 为 SkillSpec 数据模型，并校验 ID 一致性
    2. 动态导入 ``run.py``，提取其中的 ``async def run(ctx)`` 函数
    3. 用权限和工具白名单包装原始 runner，生成受限的执行上下文
    4. 读取 ``skill.md`` 文档内容
    5. 将以上信息组装为 LoadedSkill 冻结数据类

加载完成后，LoadedSkill 包含技能运行所需的全部信息，可交由注册表管理。
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Awaitable, Callable

import yaml

from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput
from src.dynamic_os.contracts.skill_spec import SkillSpec
from src.dynamic_os.skills.discovery import DiscoveredSkill, validate_skill_package

# 技能执行函数的类型签名：接收 SkillContext，返回异步 SkillOutput
SkillRunner = Callable[[SkillContext], Awaitable[SkillOutput]]


@dataclass(frozen=True)
class LoadedSkill:
    """已完整加载、可直接执行的技能。

    属性
    ----------
    spec : SkillSpec
        从 skill.yaml 解析出的技能元数据（ID、权限、适用角色、工具白名单等）。
    runner : SkillRunner
        经过权限包装的技能执行函数，调用后即运行技能逻辑。
    package_dir : Path
        技能包的目录路径，用于调试和日志定位。
    documentation : str
        skill.md 的原始文本内容，可用于向 LLM 或用户展示技能说明。
    """

    spec: SkillSpec           # 技能规格（元数据）
    runner: SkillRunner       # 包装后的异步执行函数
    package_dir: Path         # 技能包所在目录
    documentation: str        # 技能文档原文（来自 skill.md）


def load_skill_spec(discovered: DiscoveredSkill) -> SkillSpec:
    """解析并校验技能包的 skill.yaml 元数据清单。

    参数
    ----------
    discovered : DiscoveredSkill
        已发现的技能包描述。

    返回
    -------
    SkillSpec
        经 Pydantic 校验后的技能规格对象。

    异常
    ------
    ValueError
        当 skill.yaml 中声明的 ID 与目录名不一致时抛出。
        这一校验确保技能 ID 的唯一确定性：目录名即 ID。
    """
    # 先校验必需文件是否齐全
    validate_skill_package(discovered)
    payload = yaml.safe_load(discovered.manifest_path.read_text(encoding="utf-8"))
    spec = SkillSpec.model_validate(payload)
    # 强制要求 yaml 中的 id 字段与技能包目录名一致
    if spec.id != discovered.skill_id:
        raise ValueError(
            f"skill id mismatch for {discovered.package_dir}: manifest has {spec.id}, directory has {discovered.skill_id}"
        )
    return spec


def load_skill_runner(discovered: DiscoveredSkill, spec: SkillSpec) -> SkillRunner:
    """动态导入技能的 run.py 模块并提取 run 函数。

    为避免不同技能包中同名模块产生冲突，使用技能包路径的 SHA1 哈希
    作为模块名后缀，确保每个技能模块在 sys.modules 中拥有唯一键名。

    参数
    ----------
    discovered : DiscoveredSkill
        已发现的技能包描述。
    spec : SkillSpec
        已解析的技能规格（用于在错误信息中引用技能 ID）。

    返回
    -------
    SkillRunner
        run.py 中定义的 ``async def run(ctx)`` 函数引用。

    异常
    ------
    ImportError
        当 run.py 无法被 importlib 加载时抛出。
    TypeError
        当 run.py 中的 ``run`` 不是异步函数时抛出。
    """
    # 用目录路径的哈希值生成唯一模块名，防止多个技能的 run.py 互相覆盖
    module_suffix = hashlib.sha1(str(discovered.package_dir.resolve()).encode("utf-8")).hexdigest()[:12]
    module_name = f"src.dynamic_os.skills.loaded.{spec.id}_{module_suffix}"
    module_spec = importlib.util.spec_from_file_location(module_name, discovered.run_path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"unable to load skill module from {discovered.run_path}")

    # 动态创建模块对象并执行其代码
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    module_spec.loader.exec_module(module)

    # 提取 run 函数并验证其为异步函数
    runner = getattr(module, "run")
    if not inspect.iscoroutinefunction(runner):
        raise TypeError(f"skill {spec.id} must define 'async def run(ctx)'")
    return runner


def load_skill(discovered: DiscoveredSkill) -> LoadedSkill:
    """完整加载一个技能包：解析元数据、导入执行函数、读取文档。

    该函数是加载流程的主入口。它在原始 runner 外层包裹一个权限适配器，
    确保技能执行时只能访问 skill.yaml 中声明的权限和工具。

    参数
    ----------
    discovered : DiscoveredSkill
        已发现的技能包描述。

    返回
    -------
    LoadedSkill
        包含规格、执行函数、目录路径和文档的完整技能对象。
    """
    spec = load_skill_spec(discovered)
    raw_runner = load_skill_runner(discovered, spec)

    # 包装原始 runner：根据 skill.yaml 中声明的权限和工具白名单
    # 创建受限的 SkillContext，实现技能级别的权限隔离
    async def runner(ctx: SkillContext) -> SkillOutput:
        scoped_ctx = replace(
            ctx,
            tools=ctx.tools.with_permissions(spec.permissions).with_allowed_tools(spec.allowed_tools),
        )
        return await raw_runner(scoped_ctx)

    return LoadedSkill(
        spec=spec,
        runner=runner,
        package_dir=discovered.package_dir,
        documentation=discovered.doc_path.read_text(encoding="utf-8"),
    )
