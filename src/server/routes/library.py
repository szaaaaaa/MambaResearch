"""LibraryTab 后端路由——浏览 Zotero 远端 library。

端点：
- ``GET /api/library/zotero/collections``                列 collection
- ``GET /api/library/zotero/items?collection=&query=``   搜 / 列 items

凭据缺失时返回 502（Bad Gateway）+ 引导 message，让前端给"去配置"按钮。

不内置 download 端点——"拉到 workspace" action 走 prompt 注入让 Claude
调 mcp__mamba_zotero 工具完成（与 Task 8 file action bar 同语义）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.server.integrations.zotero.client import ZoteroClient
from src.server.integrations.zotero.credentials import ZoteroCredentialsMissing


router = APIRouter()


def _client() -> ZoteroClient:
    try:
        return ZoteroClient()
    except ZoteroCredentialsMissing as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
