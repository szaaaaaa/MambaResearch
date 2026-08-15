"""Registry 驱动的 backend 认证聚合与通用 API key 探测。"""

from __future__ import annotations

import asyncio
import os

from src.server.kernel.contracts import TerminalBackend


def probe_openai_api_key(env: dict[str, str] | None = None) -> bool:
    """检测 ``OPENAI_API_KEY`` env 是否非空。"""
    source = env if env is not None else os.environ
    return bool((source.get("OPENAI_API_KEY") or "").strip())


async def probe_backends(
    backends: tuple[TerminalBackend, ...],
) -> dict[str, dict[str, object]]:
    probes = await asyncio.gather(*(backend.probe_auth() for backend in backends))
    return {
        backend.descriptor.id: {
            "status": probe.status.value,
            "detail": dict(probe.detail),
        }
        for backend, probe in zip(backends, probes, strict=True)
    }
