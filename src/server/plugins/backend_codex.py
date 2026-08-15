"""Batch 1 中 Codex 进程级资源的生命周期适配器。"""

from __future__ import annotations

from src.server.codex.session_manager import codex_session_manager
from src.server.kernel.contracts import AsyncDisposer, KernelContext, PluginManifest


class CodexBackendPlugin:
    manifest = PluginManifest(id="backend.codex")

    def register(self, context: KernelContext) -> None:
        context.plugin_config(self.manifest.id)

    async def start(self, context: KernelContext) -> AsyncDisposer:
        async def dispose() -> None:
            await codex_session_manager.shutdown()

        return dispose
