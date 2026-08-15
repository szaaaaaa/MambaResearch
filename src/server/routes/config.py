"""Credential API routes."""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.common.config_utils import read_env_file
from src.server.settings import CREDENTIAL_KEYS, ENV_PATH


router = APIRouter()


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
        source = "both" if in_env and in_file else "environment" if in_env else "dotenv" if in_file else "missing"
        status[key] = {"present": in_env or in_file, "source": source}
    return status


@router.get("/api/credentials")
def get_credentials() -> dict[str, object]:
    saved_values = _read_env_file()
    return {
        "values": {key: "" for key in CREDENTIAL_KEYS},
        "status": _credential_status(saved_values),
    }


@router.post("/api/credentials")
async def save_credentials(request: Request) -> dict[str, object]:
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
        else:
            next_values.pop(key, None)
    _write_env_file(next_values)
    return {
        "values": {key: "" for key in CREDENTIAL_KEYS},
        "status": _credential_status(next_values),
    }
