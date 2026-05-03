"""Project Registry HTTP 路由。

端点：
- ``GET    /api/projects``                  列出全部项目 + active
- ``GET    /api/projects/active``           当前 active 项目；无则 404
- ``POST   /api/projects``                  注册新项目（自动激活）
- ``PUT    /api/projects/{id}/activate``    将指定项目设为 active
- ``DELETE /api/projects/{id}``             从注册表删除（不删物理目录）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.server.projects.cleanup import cleanup_project_data
from src.server.projects.models import ProjectCreate
from src.server.projects.registry import (
    ProjectNotFoundError,
    ProjectPathError,
    get_registry,
)
from src.server.projects.workspace import (
    WorkspaceError,
    add_source_dir,
)


router = APIRouter()


@router.get("/api/projects")
def list_projects() -> dict:
    state = get_registry().list_projects()
    return state.model_dump()


@router.get("/api/projects/active")
def get_active_project() -> dict:
    project = get_registry().get_active()
    if project is None:
        raise HTTPException(status_code=404, detail="no active project")
    return project.model_dump()


@router.post("/api/projects")
async def create_project(request: Request) -> dict:
    payload = await _parse_json(request)
    try:
        body = ProjectCreate.model_validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    registry = get_registry()
    try:
        project = registry.create_project(name=body.name, path=body.path)
    except ProjectPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 创建后立即激活——大方向 plan 锁定的"新建即进入"流程
    registry.activate_project(project.id)
    # 默认把项目根目录加为首个 source_dir。让用户从"新建项目 → 看到 bucket
    # 列出文件"零配置；scanner 自带 .git / node_modules / venv 黑名单，root
    # 整盘扫不会爆。用户后续可在设置里换更窄的 source_dirs。失败（路径权限
    # 异常等）只记 warning 不阻塞——空 source_dirs 仍会让 bucket 走原有的
    # "no_source_dirs" 引导态。
    try:
        add_source_dir(project.path, project.path)
    except WorkspaceError:
        # path 校验已在 registry.create_project 通过；这里失败只能是写盘权限
        # 类问题，吞掉即可
        pass
    return project.model_dump()


@router.put("/api/projects/{project_id}/activate")
def activate_project(project_id: str) -> dict:
    try:
        project = get_registry().activate_project(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return project.model_dump()


@router.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict:
    """删除项目 —— 级联清 mamba.db 中关联的对话 / 消息 / MCP 调用 / 实验记录。

    顺序：
    1. ``cleanup_project_data`` —— 先把 mamba.db 关联行清掉，避免 registry
       已删 project 后 cleanup 失败造成 orphan
    2. ``registry.delete_project`` —— 从 ``projects.json`` 移除 + 处理 active

    **不动**：物理目录 / 项目内 ``.mambaresearch/`` 工作区文件 / backend 自己
    的 JSONL（claude code / codex 仍可通过原生 CLI ``--resume`` 打开）。
    """
    try:
        get_registry().get_project(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    summary = cleanup_project_data(project_id)
    try:
        get_registry().delete_project(project_id)
    except ProjectNotFoundError as exc:
        # 罕见竞态：cleanup 期间 registry 被另一进程删了——cleanup 已完成，
        # 不报 500，让 caller 把 404 视为"项目已不在"
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "status": "deleted",
        "id": project_id,
        "cleaned": summary.to_dict(),
    }


async def _parse_json(request: Request) -> dict:
    import json as _json

    try:
        payload = await request.json()
    except _json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return payload
