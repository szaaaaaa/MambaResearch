"""Workspace 配置 + 文件分类 HTTP 路由。

所有端点隐式作用于当前 active project；无 active 时返回 409。

端点：
- ``GET    /api/workspace``                     workspace 配置
- ``POST   /api/workspace/source-dirs``         加源目录 ``{path}``
- ``DELETE /api/workspace/source-dirs``         删源目录 ``{path}``
- ``POST   /api/workspace/scan``                扫描源目录入库（不分类）
- ``GET    /api/workspace/stats``               分类索引概览
- ``GET    /api/workspace/files``               按 bucket / subtype 列文件
- ``POST   /api/workspace/files/override``      用户手动校正 bucket
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from src.server.projects.registry import get_registry
from src.server.projects.workspace import (
    WorkspacePathError,
    add_source_dir,
    load_workspace,
    remove_source_dir,
)
from src.server.workspace.classification import (
    PRIMARY_BUCKETS,
    get_db_for_project,
)
from src.server.workspace.scanner import scan_source_dir


router = APIRouter()


def _require_active_project_path() -> str:
    project = get_registry().get_active()
    if project is None:
        raise HTTPException(status_code=409, detail="no active project")
    return project.path


@router.get("/api/workspace")
def get_workspace() -> dict:
    project_path = _require_active_project_path()
    config = load_workspace(project_path)
    return config.to_dict()


@router.post("/api/workspace/source-dirs")
async def add_source(request: Request) -> dict:
    project_path = _require_active_project_path()
    payload = await _parse_json(request)
    raw = payload.get("path")
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=400, detail="path is required")
    try:
        config = add_source_dir(project_path, raw.strip())
    except WorkspacePathError as exc:
        # 路径不存在 / 不是目录 → 400；已存在 → 409
        message = str(exc)
        if "已存在" in message:
            raise HTTPException(status_code=409, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    return config.to_dict()


@router.delete("/api/workspace/source-dirs")
async def remove_source(request: Request) -> dict:
    project_path = _require_active_project_path()
    payload = await _parse_json(request)
    raw = payload.get("path")
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=400, detail="path is required")
    try:
        config = remove_source_dir(project_path, raw.strip())
    except WorkspacePathError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return config.to_dict()


@router.post("/api/workspace/scan")
async def scan(request: Request) -> dict:
    """扫描指定 source_dir（或全部已配置 source_dirs）入库。

    Body: ``{source_dir?: str}``——给定时只扫该目录；未给时扫所有 workspace
    配置的源目录，结果合并。
    """
    project_path = _require_active_project_path()
    payload = await _parse_json(request)
    source_dir_raw = payload.get("source_dir")
    db = get_db_for_project(project_path)

    sources: list[str]
    if isinstance(source_dir_raw, str) and source_dir_raw.strip():
        sources = [source_dir_raw.strip()]
    else:
        config = load_workspace(project_path)
        sources = list(config.source_dirs)
    if not sources:
        raise HTTPException(
            status_code=400,
            detail="workspace 未配置 source_dirs；先添加源目录或在请求体里指定 source_dir",
        )

    # 简单顺序扫描——大目录由 scanner 内部黑名单 + 上限保护
    aggregate = {
        "scanned": 0,
        "new": 0,
        "changed": 0,
        "unchanged": 0,
        "skipped_large": 0,
        "skipped_dirs_count": 0,
        "truncated": False,
        "duration_s": 0.0,
        "per_source": [],
    }
    for src in sources:
        try:
            result = scan_source_dir(db, src)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        d = result.to_dict()
        d["source_dir"] = src
        aggregate["per_source"].append(d)
        aggregate["scanned"] += d["scanned"]
        aggregate["new"] += d["new"]
        aggregate["changed"] += d["changed"]
        aggregate["unchanged"] += d["unchanged"]
        aggregate["skipped_large"] += d["skipped_large"]
        aggregate["skipped_dirs_count"] += d["skipped_dirs_count"]
        aggregate["truncated"] = aggregate["truncated"] or d["truncated"]
        aggregate["duration_s"] += d["duration_s"]
    aggregate["duration_s"] = round(aggregate["duration_s"], 2)
    return aggregate


@router.get("/api/workspace/stats")
def stats() -> dict:
    project_path = _require_active_project_path()
    db = get_db_for_project(project_path)
    return db.stats().to_dict()


@router.get("/api/workspace/files")
def list_files(
    bucket: str | None = Query(default=None),
    subtype: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict:
    project_path = _require_active_project_path()
    if bucket is not None and bucket not in PRIMARY_BUCKETS:
        raise HTTPException(
            status_code=400,
            detail=f"invalid bucket: {bucket!r} (must be one of {sorted(PRIMARY_BUCKETS)})",
        )
    db = get_db_for_project(project_path)
    rows = db.list_by_bucket(bucket, subtype=subtype, limit=limit)
    return {"files": [r.to_dict() for r in rows]}


@router.post("/api/workspace/files/override")
async def file_override(request: Request) -> dict:
    """用户手动校正某文件的分类。"""
    project_path = _require_active_project_path()
    payload = await _parse_json(request)
    path = payload.get("path")
    bucket = payload.get("primary_bucket")
    subtype = payload.get("subtype")
    tags = payload.get("tags") or []
    if not isinstance(path, str) or not path.strip():
        raise HTTPException(status_code=400, detail="path is required")
    if not isinstance(bucket, str) or bucket not in PRIMARY_BUCKETS:
        raise HTTPException(
            status_code=400,
            detail=f"primary_bucket must be one of {sorted(PRIMARY_BUCKETS)}",
        )
    if subtype is not None and not isinstance(subtype, str):
        raise HTTPException(status_code=400, detail="subtype must be string or null")
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        raise HTTPException(status_code=400, detail="tags must be list of strings")
    db = get_db_for_project(project_path)
    ok = db.set_user_override(path.strip(), bucket, subtype=subtype, tags=tags)
    if not ok:
        raise HTTPException(status_code=404, detail="file not found in classification index")
    return {"status": "ok", "path": path.strip(), "primary_bucket": bucket}


async def _parse_json(request: Request) -> dict:
    import json as _json

    try:
        payload = await request.json()
    except _json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return payload
