"""自定义技能配置模块 — 加载项目级别的角色-技能附加映射。

本模块允许用户在项目工作目录下通过 ``skills/skills_config.yaml``
文件为角色追加额外的技能绑定，而无需修改系统核心配置。

配置文件格式示例::

    role_skill_additions:
      researcher:
        - custom_search
        - data_analysis
      engineer:
        - code_review

该机制使得用户可以在不改动内置角色定义的情况下，
灵活地为角色扩展可用技能列表。
"""

from __future__ import annotations

from pathlib import Path

import yaml


def load_custom_skill_additions(cwd: Path) -> dict[str, list[str]]:
    """从项目目录加载角色到技能的附加映射配置。

    读取 ``<cwd>/skills/skills_config.yaml`` 中的 ``role_skill_additions``
    字段，将其解析为 ``{角色ID: [技能ID列表]}`` 的字典。

    参数
    ----------
    cwd : Path
        当前工作目录（项目根目录）。

    返回
    -------
    dict[str, list[str]]
        角色 ID 到附加技能 ID 列表的映射。
        若配置文件不存在或格式不合法，返回空字典。
    """
    config_path = cwd / "skills" / "skills_config.yaml"
    # 配置文件不存在时静默返回空映射，不视为错误
    if not config_path.is_file():
        return {}
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    # 顶层必须是字典
    if not isinstance(raw, dict):
        return {}
    additions = raw.get("role_skill_additions")
    # role_skill_additions 字段必须是字典
    if not isinstance(additions, dict):
        return {}
    # 逐项提取，仅保留值为列表类型的合法条目
    result: dict[str, list[str]] = {}
    for role_id, skills in additions.items():
        if isinstance(skills, list):
            result[str(role_id)] = [str(s) for s in skills]
    return result
