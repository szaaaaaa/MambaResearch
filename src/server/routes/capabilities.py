"""Kernel capability inventory HTTP 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Request


router = APIRouter()


@router.get("/api/capabilities")
def get_capabilities(request: Request) -> dict:
    kernel = request.app.state.kernel
    snapshot = kernel.snapshot()
    return {
        "api_version": 2,
        "enabled_plugins": list(snapshot.enabled_plugins),
        "execution_host": "codex_app",
    }
