"""LibraryTab 后端路由——浏览 + 下载 Zotero 远端 library。

端点：
- ``GET  /api/library/zotero/collections``                列 collection
- ``GET  /api/library/zotero/items?collection=&query=``   搜 / 列 items
- ``POST /api/library/zotero/import``                     下载 item PDF 到本地

凭据缺失时返回 502（Bad Gateway）+ 引导 message，让前端给"去配置"按钮。

import 端点直接调 ``ZoteroClient.download_attachment`` 写盘到 ``dest_dir``
（不传则默认 active project 根 + ``zotero_imports/``）；MCP ``download_pdf``
工具留给 Claude PTY 走自然语言决策（譬如指定特定 collection 子目录）。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.server.integrations.zotero.client import ZoteroClient
from src.server.integrations.zotero.credentials import ZoteroCredentialsMissing
from src.server.projects.registry import get_registry


router = APIRouter()

DEFAULT_IMPORT_SUBDIR = "zotero_imports"


def _client() -> ZoteroClient:
    try:
        return ZoteroClient()
    except ZoteroCredentialsMissing as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _resolve_import_dest(dest_dir: str | None) -> Path:
    """决定 ``download_attachment`` 落盘目录。

    显式传 ``dest_dir`` 优先；否则取 active project 根 + ``zotero_imports/``。
    缺 active project 又没传 ``dest_dir`` 时抛 400，让前端先选项目。
    """
    if dest_dir:
        return Path(dest_dir)
    active = get_registry().get_active()
    if active is None:
        raise HTTPException(
            status_code=400,
            detail="no active project; pass dest_dir explicitly or activate a project first",
        )
    return Path(active.path) / DEFAULT_IMPORT_SUBDIR


class ImportRequest(BaseModel):
    item_key: str = Field(..., min_length=1, description="Zotero item key")
    dest_dir: str | None = Field(
        default=None,
        description="目标目录绝对路径；缺省落到 <active project>/zotero_imports/",
    )
    filename: str | None = Field(
        default=None, description="可选写盘文件名；缺省用 attachment 自身 filename"
    )


@router.get("/api/library/zotero/collections")
def list_collections() -> dict:
    client = _client()
    try:
        items = client.list_collections()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Zotero 列 collection 失败：{exc}") from exc
    return {"collections": items}


@router.get("/api/library/zotero/items")
def list_items(
    query: str = Query("", description="留空则列最近 limit 条"),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    client = _client()
    try:
        # ZoteroClient.search 需 query；空 query 用 "" 也能 work（返回最近 N 条）
        items = client.search(query, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Zotero 搜索失败：{exc}") from exc
    return {"items": items, "query": query, "limit": limit}


@router.post("/api/library/zotero/import")
def import_item(payload: ImportRequest) -> dict:
    """下载 Zotero item 关联 PDF 到本地，让下次 workspace scan 收编为 literature。"""
    client = _client()
    dest = _resolve_import_dest(payload.dest_dir)
    try:
        result = client.download_attachment(
            payload.item_key, dest, filename=payload.filename
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Zotero 下载失败：{exc}"
        ) from exc
    if not result.get("ok"):
        raise HTTPException(
            status_code=502,
            detail=f"Zotero 下载失败：{result.get('error', 'unknown')}",
        )
    return result
