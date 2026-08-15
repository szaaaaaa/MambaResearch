"""当前启用 backend 的认证状态路由。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from src.server.auth.probe import probe_backends, probe_openai_api_key


router = APIRouter()


@router.get("/api/auth/status")
async def get_auth_status(request: Request) -> dict:
    backends = request.app.state.kernel.context.capabilities.backends.list()
    return {
        "backends": await probe_backends(backends),
        "api_keys": {"openai": probe_openai_api_key()},
    }
