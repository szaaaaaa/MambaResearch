"""将现有 HTTP 路由和核心进程资源接入 Mamba Kernel。"""

from __future__ import annotations

from fastapi import APIRouter

from src.server.kernel.contracts import AsyncDisposer, KernelContext, PluginManifest
from src.server.projects.db import get_db, init_mamba_db
from src.server.routes.capabilities import router as capabilities_router
from src.server.routes.conversations import router as conversations_router
from src.server.routes.history_runs import router as history_runs_router
from src.server.routes.experiments import router as experiments_router
from src.server.routes.literature import router as literature_router
from src.server.routes.projects import router as projects_router

router = APIRouter()
for _router in (
    projects_router,
    capabilities_router,
    conversations_router,
    literature_router,
    history_runs_router,
    experiments_router,
):
    router.include_router(_router)


class CoreHttpPlugin:
    manifest = PluginManifest(id="core.http")

    def register(self, context: KernelContext) -> None:
        context.capabilities.http.register(
            contribution_id=self.manifest.id,
            plugin_id=self.manifest.id,
            router=router,
        )

    async def start(self, context: KernelContext) -> AsyncDisposer:
        init_mamba_db()
        async def dispose() -> None:
            get_db().close()

        return dispose
