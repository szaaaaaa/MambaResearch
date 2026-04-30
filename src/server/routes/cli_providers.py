"""Claude Code provider 注册表 HTTP 路由（D+E 重构 task 2）。

settings UI 的 "CLI" 视图通过这两个端点读写 ``configs/claude_code/providers.json``：

- ``GET  /api/cli-providers``           返回完整注册表
- ``PATCH /api/cli-providers``          按 provider name 合并更新单个/多个条目

PATCH 语义
~~~~~~~~~~

Body 形状 ``{"<provider_name>": {"base_url"?, "api_key_env"?, "default_model"?}}``。

- 列出的 provider 存在 → 字段级合并（partial update，未给的字段保留）
- 列出的 provider 不存在 → 创建新条目（必须三字段全提供，否则 400）
- 删除 provider 用单独 ``DELETE /api/cli-providers/{name}`` —— 不通过 PATCH 传 null

写回后清空 ``providers`` 模块的 registry 缓存，下次 session 创建走的是新值。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.server.claude_code.providers import (
    REQUIRED_FIELDS,
    ProviderRegistryError,
    load_provider_registry,
    reset_provider_registry_cache,
)
from src.server.settings import CLAUDE_CODE_PROVIDERS_PATH


router = APIRouter()


def _read_providers_file() -> dict[str, dict[str, str]]:
    """读 providers.json；不存在返回空 dict，损坏返回 500（user 该手修文件）。"""
    if not CLAUDE_CODE_PROVIDERS_PATH.exists():
        return {}
    try:
        with CLAUDE_CODE_PROVIDERS_PATH.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"failed to read providers.json: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=500,
            detail="providers.json must contain a JSON object",
        )
    return payload


def _write_providers_file(payload: dict[str, dict[str, str]]) -> None:
    CLAUDE_CODE_PROVIDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CLAUDE_CODE_PROVIDERS_PATH.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, ensure_ascii=False, sort_keys=False)
        fp.write("\n")


@router.get("/api/cli-providers")
def list_cli_providers() -> dict[str, Any]:
    return {"providers": _read_providers_file()}


@router.patch("/api/cli-providers")
async def patch_cli_providers(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400, detail="request body must be a JSON object"
        )

    current = _read_providers_file()
    for name, updates in body.items():
        if not isinstance(name, str) or not name:
            raise HTTPException(
                status_code=400, detail="provider name must be non-empty string"
            )
        if not isinstance(updates, dict):
            raise HTTPException(
                status_code=400,
                detail=f"provider {name!r}: updates must be a JSON object",
            )
        existing = current.get(name)
        if existing is None:
            # 新增条目要求 3 个必填字段全到位
            missing = [f for f in REQUIRED_FIELDS if f not in updates]
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"creating new provider {name!r}: required fields "
                        f"missing: {missing}"
                    ),
                )
            existing = {}
        merged = {**existing, **updates}
        current[name] = merged

    # 验证合并后整体仍合法（拒绝把已存在 provider 的字段改成非字符串）
    try:
        load_provider_registry(current)
    except ProviderRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _write_providers_file(current)
    reset_provider_registry_cache()
    return {"providers": current}
