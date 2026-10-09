"""Workspace 文件分类索引 + 扫描器。

每个 project 独立一份 ``<project>/.mambaresearch/classification.db``——与
``mamba.db``（项目无关的会话头）分离，便于跨项目独立备份/迁移。

模块组织：
- ``classification`` — SQLite schema + CRUD
- ``scanner`` — 增量扫描源目录（mtime + sha256），不分类
- ``mcp_server`` —（Stage 2 Task 2 引入）workspace.* MCP 工具
"""

from src.server.workspace.classification import (
    ClassificationDb,
    ClassificationStats,
    FileEntry,
    PRIMARY_BUCKETS,
    get_db_for_project,
)

__all__ = [
    "ClassificationDb",
    "ClassificationStats",
    "FileEntry",
    "PRIMARY_BUCKETS",
    "get_db_for_project",
]
