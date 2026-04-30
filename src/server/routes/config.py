"""配置与凭证 API 路由（D+E 重构后版本）。

枢转后 ``configs/agent.yaml`` 已物理删除，全局配置拆为：

- ``configs/claude_code/providers.json`` —— Claude Code provider 注册表
- ``configs/codex/auth.json`` —— Codex OAuth 绑定（default_profile / allowed_profiles 等）
- ``configs/mcp/env_overrides.json`` —— MCP server 的 user 级 env override
- ``.env`` —— 凭证（API keys）

本模块只承担 Codex auth 与凭证 (.env) 两类路由：

- ``/api/codex/{status,login,logout,callback}`` —— 把 ``codex/auth.json`` 包装成
  legacy 形状传给 ``src/common/openai_codex`` 的 binding 函数（保持其
  ``cfg["auth"]["openai_codex"]`` 接口契约）
- ``/api/credentials`` (GET/POST) —— 读写 ``.env`` 中的 API keys

旧 ``/api/config`` GET/POST 已删除——其 yaml 全局视图在新架构里没有对应物
（providers / mcp / codex 各有独立路由，settings UI 走 4 个分视图）。
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.common.config_utils import read_env_file
from src.common.openai_codex import (
    complete_openai_codex_login,
    logout_openai_codex,
    openai_codex_login_status,
    start_openai_codex_login,
)
from src.server.settings import CODEX_AUTH_PATH, CREDENTIAL_KEYS, ENV_PATH


router = APIRouter()


def _load_codex_legacy_config() -> dict[str, Any]:
    """读 ``codex/auth.json`` 包装成 legacy ``cfg["auth"]["openai_codex"]`` 形状。

    ``src/common/openai_codex`` 的 ``_openai_codex_binding(config)`` 期望
    ``cfg["auth"]["openai_codex"]`` 路径。改它的接口影响面大，保留旧形状作
    适配层——本函数把扁平的 ``codex/auth.json`` 内容重新包成嵌套 dict 传入。

    文件不存在返回 ``{"auth": {"openai_codex": {}}}``——binding 会用默认值兜底。
    """
    if not CODEX_AUTH_PATH.exists():
        return {"auth": {"openai_codex": {}}}
    with CODEX_AUTH_PATH.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=500,
            detail=f"{CODEX_AUTH_PATH.name} must contain a JSON object",
        )
    return {"auth": {"openai_codex": payload}}


def _read_env_file() -> dict[str, str]:
    return read_env_file(ENV_PATH)


def _write_env_file(values: dict[str, str]) -> None:
    existing_lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    remaining = {key: str(value).strip() for key, value in values.items() if str(value).strip()}
    written_keys: set[str] = set()
    output_lines: list[str] = []

    for raw_line in existing_lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in raw_line:
            output_lines.append(raw_line)
            continue
        key, _ = raw_line.split("=", 1)
        normalized_key = key.strip()
        if normalized_key not in CREDENTIAL_KEYS:
            output_lines.append(raw_line)
            continue
        next_value = remaining.get(normalized_key, "")
        if not next_value:
            written_keys.add(normalized_key)
            continue
        output_lines.append(f"{normalized_key}={json.dumps(next_value, ensure_ascii=False)}")
        written_keys.add(normalized_key)

    for key in CREDENTIAL_KEYS:
        if key in written_keys:
            continue
        next_value = remaining.get(key, "")
        if next_value:
            output_lines.append(f"{key}={json.dumps(next_value, ensure_ascii=False)}")

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("\n".join(output_lines).rstrip() + ("\n" if output_lines else ""), encoding="utf-8")


def _credential_status(values: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    saved_values = values if values is not None else _read_env_file()
    status: dict[str, dict[str, Any]] = {}
    for key in CREDENTIAL_KEYS:
        in_env = bool(str(os.environ.get(key, "")).strip())
        in_file = bool(str(saved_values.get(key, "")).strip())
        if in_env and in_file:
            source = "both"
        elif in_env:
            source = "environment"
        elif in_file:
            source = "dotenv"
        else:
            source = "missing"
        status[key] = {
            "present": in_env or in_file,
            "source": source,
        }
    return status


@router.get("/api/credentials")
def get_credentials():
    saved_values = _read_env_file()
    return {
        "values": {key: "" for key in CREDENTIAL_KEYS},
        "status": _credential_status(saved_values),
    }


@router.get("/api/codex/status")
def get_codex_status():
    return openai_codex_login_status(config=_load_codex_legacy_config())


@router.post("/api/codex/login")
def start_codex_login():
    config = _load_codex_legacy_config()
    try:
        payload = start_openai_codex_login(config=config)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    status = payload.get("status")
    if not isinstance(status, dict):
        status = openai_codex_login_status(config=config, refresh_if_needed=False)
    return {
        "message": "OpenAI Codex OAuth login is ready. Finish the browser flow, then refresh status.",
        "authorize_url": payload.get("authorize_url", ""),
        "status": status,
    }


@router.post("/api/codex/logout")
def logout_codex():
    config = _load_codex_legacy_config()
    try:
        status = logout_openai_codex(config=config)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "message": "OpenAI Codex OAuth login has been cleared.",
        "status": status,
    }


@router.post("/api/codex/callback")
async def complete_codex_login(request: Request):
    config = _load_codex_legacy_config()
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="callback payload must be an object")
    callback_input = str(
        payload.get("callback_input")
        or payload.get("callback_url")
        or payload.get("code")
        or ""
    ).strip()
    if not callback_input:
        raise HTTPException(status_code=400, detail="callback_input is required")
    try:
        status = complete_openai_codex_login(callback_input, config=config)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "message": "OpenAI Codex OAuth login has been completed.",
        "status": status,
    }


@router.post("/api/credentials")
async def save_credentials(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="credentials payload must be an object")
    next_values = _read_env_file()
    for key in CREDENTIAL_KEYS:
        if key not in payload:
            continue
        value = str(payload.get(key, "")).strip()
        if value:
            next_values[key] = value
        elif key in next_values:
            del next_values[key]
    _write_env_file(next_values)
    return {
        "values": {key: "" for key in CREDENTIAL_KEYS},
        "status": _credential_status(next_values),
    }
