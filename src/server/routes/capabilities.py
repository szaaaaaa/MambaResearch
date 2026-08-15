"""Kernel capability inventory HTTP 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Request


router = APIRouter()


@router.get("/api/capabilities")
def get_capabilities(request: Request) -> dict:
    kernel = request.app.state.kernel
    snapshot = kernel.snapshot()
    return {
        "api_version": snapshot.api_version,
        "enabled_plugins": list(snapshot.enabled_plugins),
        "backends": [
            {
                "id": backend.descriptor.id,
                "label": backend.descriptor.label,
                "supports_resume": backend.descriptor.supports_resume,
                "supports_provider_selection": backend.descriptor.supports_provider_selection,
            }
            for backend in kernel.context.capabilities.backends.list()
        ],
    }
