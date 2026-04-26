"""Project 实体的 Pydantic schema。

这些类型在路由层（``src/server/routes/projects.py``）和注册表
（``src/server/projects/registry.py``）之间传递；持久化格式即下方
``Project.model_dump`` 的 JSON 表达，可直接落到 ``projects.json``。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Project(BaseModel):
    """已注册的研究项目。

    Attributes
    ----------
    id : str
        项目唯一 id（uuid hex）。注册表创建时分配，外部不应自行构造。
    name : str
        用户可见名称，可重复。
    path : str
        绝对路径（OS 原生分隔符）。注册时校验存在且为目录。允许位于仓库外。
    created_at : int
        注册 Unix 时间戳（秒）。
    last_active_at : int
        最近一次被激活的时间戳（秒）；从未激活过的项目与 created_at 相同。
    """

    id: str
    name: str
    path: str
    created_at: int
    last_active_at: int


class ProjectCreate(BaseModel):
    """``POST /api/projects`` 请求体。"""

    name: str = Field(min_length=1, max_length=200)
    path: str = Field(min_length=1)


class ProjectsState(BaseModel):
    """``projects.json`` 的顶层结构。"""

    projects: list[Project] = Field(default_factory=list)
    active_project_id: str | None = None
