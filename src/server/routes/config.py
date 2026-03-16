import json
import os
from copy import deepcopy
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request

from src.common.openai_codex import (
    complete_openai_codex_login,
    logout_openai_codex,
    openai_codex_login_status,
    start_openai_codex_login,
)
from src.dynamic_os.tools.backends import ConfiguredLLMClient
from src.server.settings import APP_RUNTIME_MODE, CONFIG_PATH, CREDENTIAL_KEYS, ENV_PATH


router = APIRouter()


def _normalize_config_shape(config: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(config)
    llm_config = normalized.get("llm")
    if isinstance(llm_config, dict):
        role_models = llm_config.get("role_models")
        if isinstance(role_models, dict):
            legacy_critic = role_models.pop("critic", None)
            reviewer_entry = role_models.get("reviewer")
            if legacy_critic and not isinstance(reviewer_entry, dict):
                role_models["reviewer"] = legacy_critic

            conductor_entry = role_models.get("conductor")
            agent_config = normalized.get("agent")
            if isinstance(agent_config, dict):
                routing_config = agent_config.get("routing")
                if not isinstance(routing_config, dict):
                    routing_config = {}
                    agent_config["routing"] = routing_config
                planner_config = routing_config.get("planner_llm")
                if not isinstance(planner_config, dict):
                    planner_config = {}
                    routing_config["planner_llm"] = planner_config
                if isinstance(conductor_entry, dict):
                    planner_config.setdefault("provider", conductor_entry.get("provider", ""))
                    planner_config.setdefault("model", conductor_entry.get("model", ""))
                planner_config.setdefault("temperature", 0.1)
    return normalized


def _read_config_file() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}
    if not isinstance(config, dict):
        raise HTTPException(status_code=500, detail="config file must contain an object")
    return _normalize_config_shape(config)


def _merge_config(base: Any, incoming: Any) -> Any:
    if isinstance(base, dict) and isinstance(incoming, dict):
        merged = dict(base)
        for key, value in incoming.items():
            merged[key] = _merge_config(merged.get(key), value)
        return merged
    if isinstance(incoming, list):
        return list(incoming)
    return incoming


def _write_config_file(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as file:
        yaml.safe_dump(_normalize_config_shape(config), file, allow_unicode=True, sort_keys=False)


@router.get("/api/config")
def get_config():
    config = _read_config_file()
    return {**config, "runtime_mode": APP_RUNTIME_MODE}


@router.post("/api/config")
async def save_config(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="config payload must be an object")
    incoming = dict(payload)
    incoming.pop("runtime_mode", None)
    merged_config = _merge_config(_read_config_file(), incoming)
    normalized = _normalize_config_shape(merged_config)
    _write_config_file(normalized)
    return {**normalized, "runtime_mode": APP_RUNTIME_MODE}


def _read_env_file() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed_value = value.strip().strip('"').strip("'")
        if parsed_value:
            values[key.strip()] = parsed_value
    return values


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
    return openai_codex_login_status(config=_read_config_file())


@router.post("/api/codex/login")
def start_codex_login():
    config = _read_config_file()
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
    config = _read_config_file()
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
    config = _read_config_file()
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


@router.post("/api/codex/verify")
async def verify_codex_runtime(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="verification payload must be an object")
    model = str(payload.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="model is required")

    client = ConfiguredLLMClient(
        saved_env=_read_env_file(),
        workspace_root=CONFIG_PATH.parent.parent,
        config=_read_config_file(),
    )
    try:
        result = client.complete(
            provider="openai_codex",
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly OK"}],
            temperature=0.0,
            max_tokens=16,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"codex verification failed: {exc}") from exc

    return {
        "message": "OpenAI Codex OAuth verification succeeded.",
        "model": model,
        "response_text": result.text,
        "usage": result.usage,
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
