import os
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request

from src.server.settings import APP_RUNTIME_MODE, CONFIG_PATH, CREDENTIAL_KEYS, ENV_PATH


router = APIRouter()


@router.get("/api/config")
def get_config():
    if not CONFIG_PATH.exists():
        return {"runtime_mode": APP_RUNTIME_MODE}
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}
    if not isinstance(config, dict):
        raise HTTPException(status_code=500, detail="config file must contain an object")
    return {**config, "runtime_mode": APP_RUNTIME_MODE}


@router.post("/api/config")
async def save_config(request: Request):
    del request
    raise HTTPException(status_code=405, detail="dynamic_os runtime configuration is read-only")


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
def _merge_runtime_credentials(
    *,
    base_env: dict[str, str],
    saved_credentials: dict[str, str] | None = None,
    request_credentials: dict[str, Any] | None = None,
) -> dict[str, str]:
    merged = dict(base_env)

    for key, value in (saved_credentials or {}).items():
        text = str(value).strip()
        if key in CREDENTIAL_KEYS and text and not str(merged.get(key, "")).strip():
            merged[key] = text

    if isinstance(request_credentials, dict):
        for key, value in request_credentials.items():
            text = str(value).strip()
            if key in CREDENTIAL_KEYS and text:
                merged[key] = text

    return merged


def _write_env_file(values: dict[str, str]) -> None:
    ENV_PATH.write_text(
        "".join(f'{key}="{value}"\n' for key, value in values.items()),
        encoding="utf-8",
    )


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


@router.post("/api/credentials")
async def save_credentials(request: Request):
    del request
    raise HTTPException(status_code=405, detail="dynamic_os credentials are read-only at runtime")
