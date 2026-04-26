"""Auth 状态探测路由。

端点：
- ``GET /api/auth/status`` → ``AuthProbeResult.to_dict()``
"""

from __future__ import annotations

from fastapi import APIRouter

from src.server.auth.probe import probe_all


router = APIRouter()


@router.get("/api/auth/status")
async def get_auth_status() -> dict:
    result = await probe_all()
    return result.to_dict()
