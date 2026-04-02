"""Dynamic Research OS — 技能子系统入口模块。

本模块是技能（Skill）子系统的包初始化文件，负责将子系统的核心公开接口
统一导出，方便外部代码通过一次导入即可使用技能发现、加载和注册功能。

技能子系统的整体工作流程：
    1. **发现（discovery）** — 扫描指定根目录，识别符合规范的技能包目录
    2. **加载（loader）** — 解析 skill.yaml 元数据、动态导入 run.py 入口函数
    3. **注册（registry）** — 汇总所有已加载技能，提供按 ID 查询和角色兼容性校验
"""

from src.dynamic_os.skills.discovery import DiscoveredSkill, discover_skill_packages
from src.dynamic_os.skills.loader import LoadedSkill, load_skill
from src.dynamic_os.skills.registry import SkillRegistry

__all__ = [
    "DiscoveredSkill",
    "LoadedSkill",
    "SkillRegistry",
    "discover_skill_packages",
    "load_skill",
]
