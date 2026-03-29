"""技能包发现模块 — 扫描文件系统以定位技能包目录。

本模块实现技能子系统的第一阶段：**发现**。
它遍历一组根目录（roots），将每个符合条件的子目录识别为一个"技能包"。
一个有效的技能包目录必须包含三个必需文件：
    - ``skill.yaml`` — 技能元数据清单（ID、权限、适用角色等）
    - ``skill.md``   — 技能说明文档
    - ``run.py``     — 技能执行入口（必须定义 ``async def run(ctx)``）

发现阶段只负责定位目录和基本校验，不解析文件内容。
文件内容的解析由 loader 模块完成。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


# 技能包目录中必须存在的三个文件名
REQUIRED_SKILL_FILES = ("skill.yaml", "skill.md", "run.py")


@dataclass(frozen=True)
class DiscoveredSkill:
    """已发现但尚未加载的技能包描述。

    该数据类仅记录技能包在文件系统中的位置信息，
    不包含技能的具体配置或可执行代码。

    属性
    ----------
    root : Path
        包含此技能包的根搜索目录（如 builtins/ 或 skills/）。
    package_dir : Path
        技能包自身的目录路径（如 builtins/web_search/）。
    """

    root: Path          # 技能包所属的搜索根目录
    package_dir: Path   # 技能包自身的完整目录路径

    @property
    def skill_id(self) -> str:
        """技能 ID，直接取目录名。例如目录名为 ``web_search``，则 ID 为 ``web_search``。"""
        return self.package_dir.name

    @property
    def manifest_path(self) -> Path:
        """技能元数据清单文件路径（skill.yaml）。"""
        return self.package_dir / "skill.yaml"

    @property
    def doc_path(self) -> Path:
        """技能说明文档路径（skill.md）。"""
        return self.package_dir / "skill.md"

    @property
    def run_path(self) -> Path:
        """技能执行入口脚本路径（run.py）。"""
        return self.package_dir / "run.py"


def discover_skill_packages(roots: list[str | Path]) -> list[DiscoveredSkill]:
    """扫描多个根目录，收集所有技能包。

    参数
    ----------
    roots : list[str | Path]
        要扫描的根目录列表。每个根目录下的直接子目录都会被视为潜在技能包。

    返回
    -------
    list[DiscoveredSkill]
        按目录名排序的已发现技能包列表。
        注意：此阶段不验证目录内是否包含必需文件，仅跳过以 ``__`` 开头的目录
        （如 ``__pycache__``）。
    """
    packages: list[DiscoveredSkill] = []
    for root in [Path(item) for item in roots]:
        if not root.exists():
            # 根目录不存在时静默跳过，允许可选的外部技能目录缺失
            continue
        for package_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            # 跳过 Python 内部目录（如 __pycache__）
            if package_dir.name.startswith("__"):
                continue
            packages.append(DiscoveredSkill(root=root, package_dir=package_dir))
    return packages


def validate_skill_package(discovered: DiscoveredSkill) -> None:
    """校验技能包目录中是否包含所有必需文件。

    参数
    ----------
    discovered : DiscoveredSkill
        待校验的已发现技能包。

    异常
    ------
    ValueError
        当技能包目录缺少一个或多个必需文件时抛出，
        错误消息中列出所有缺失的文件名。
    """
    missing = [name for name in REQUIRED_SKILL_FILES if not (discovered.package_dir / name).is_file()]
    if missing:
        raise ValueError(f"skill package {discovered.package_dir} is missing: {', '.join(missing)}")
