"""Per-project 配置 HTTP 路由（D+E 重构 task 3）。

settings UI 的 "项目" 视图通过这两个端点读写 active project 的本地配置：

- ``GET   /api/project-config``        返回 active project 的 config 内容；
                                        无 active project / 文件不存在 → 返回空 dict
- ``PATCH /api/project-config``        patch-merge 写入 schema 子集；
                                        无 active project → 400

Schema（最小集）：

::

    {
      "codex_profile": str,
      "enabled_mcp_servers": list[str]
    }

文件物理位置：``<project>/.mambaresearch/config.json``，与现有 ``.mambaresearch/``
项目元数据目录（classification.db 等）共存。**lazy 写入**——GET 不创建文件。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.server.projects.registry import (
    ProjectError,
    active_project_config,
    write_active_project_config,
)


router = APIRouter()


@router.get("/api/project-config")
def get_project_config() -> dict[str, Any]:
    """读 active project 配置。无 active / 文件不存在均返回空 dict。"""
    return {"config": active_project_config()}


@router.patch("/api/project-config")
async def patch_project_config(request: Request) -> dict[str, Any]:
    """patch-merge 更新 active project 配置；toml 不存在则首次创建。"""
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400, detail="request body must be a JSON object"
        )

    try:
        merged = write_active_project_config(body)
    except ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"config": merged}
