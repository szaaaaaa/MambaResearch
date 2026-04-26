"""MambaResearch 项目级实体模块。

本包负责"研究项目"（Project）这一概念的注册、激活、与持久化——和已有的
``ProjectConfig``（LLM/Provider 配置，``store.tsx`` 中字段同名）严格区分。

数据布局：
- ``~/.mambaresearch/projects.json`` — 项目注册表（全局，跨机器需手动同步）
- ``~/.mambaresearch/mamba.db`` — 会话与会话段薄表（SQLite）
- ``<project_path>/.mambaresearch/workspace.json`` — 项目内的源目录配置
- ``<project_path>/.mambaresearch/classification.db`` — 文件分类索引（Stage 2 引入）
"""

from src.server.projects.models import (
    Project,
    ProjectCreate,
    ProjectsState,
)
from src.server.projects.registry import (
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
    ProjectPathError,
    ProjectRegistry,
    get_registry,
)

__all__ = [
    "Project",
    "ProjectCreate",
    "ProjectsState",
    "ProjectRegistry",
    "ProjectAlreadyExistsError",
    "ProjectNotFoundError",
    "ProjectPathError",
    "get_registry",
]
