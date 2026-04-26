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

from src.server.projects.models import ProjectCreate
from src.server.projects.registry import (
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
    ProjectPathError,
    get_registry,
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
    except ProjectAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProjectPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 创建后立即激活——大方向 plan 锁定的"新建即进入"流程
    registry.activate_project(project.id)
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
    try:
        get_registry().delete_project(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted", "id": project_id}


async def _parse_json(request: Request) -> dict:
    import json as _json

    try:
        payload = await request.json()
    except _json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return payload
