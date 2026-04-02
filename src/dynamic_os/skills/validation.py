"""技能校验模块 — 验证动态生成的技能代码和配置。

本模块用于技能进化（skill evolution）场景：当系统动态生成新技能时，
需要在将其写入磁盘并加载之前，先验证生成的源代码和 YAML 配置是否合法。

校验内容包括：
    - 源代码的语法正确性（通过 AST 解析）
    - 是否包含必需的 ``async def run(ctx)`` 入口函数
    - run 函数是否接受至少一个参数
    - skill.yaml 内容是否符合 SkillSpec 数据模型
"""

from __future__ import annotations

import ast

import yaml

from src.dynamic_os.contracts.skill_spec import SkillSpec


def validate_skill_source(source: str) -> list[str]:
    """校验动态生成的技能源代码是否合法。

    通过 Python AST 解析检查源代码结构，确保其满足技能执行的基本要求。

    参数
    ----------
    source : str
        待校验的 Python 源代码字符串（即 run.py 的内容）。

    返回
    -------
    list[str]
        错误信息列表。若为空列表则表示校验通过。
    """
    errors: list[str] = []
    # 第一步：检查语法是否可以被 Python 解析
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        errors.append(f"Syntax error: {exc}")
        return errors

    # 第二步：遍历 AST 查找 async def run(...) 定义
    has_run = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run":
            has_run = True
            # run 函数必须至少接受一个参数（ctx: SkillContext）
            if len(node.args.args) < 1:
                errors.append("run() must accept at least one argument (ctx)")
    # 必须存在 async def run 函数
    if not has_run:
        errors.append("Missing 'async def run(ctx)' function")
    return errors


def validate_skill_yaml(yaml_content: str) -> tuple[SkillSpec | None, list[str]]:
    """校验动态生成的 skill.yaml 配置是否合法。

    尝试将 YAML 文本解析为 SkillSpec Pydantic 模型，
    若解析或校验失败则返回错误信息。

    参数
    ----------
    yaml_content : str
        待校验的 YAML 配置字符串（即 skill.yaml 的内容）。

    返回
    -------
    tuple[SkillSpec | None, list[str]]
        二元组 ``(spec, errors)``：
        - 校验通过时返回 ``(SkillSpec实例, [])``
        - 校验失败时返回 ``(None, [错误信息列表])``
    """
    errors: list[str] = []
    try:
        data = yaml.safe_load(yaml_content)
        spec = SkillSpec.model_validate(data)
        return spec, []
    except Exception as exc:
        errors.append(str(exc))
        return None, errors
