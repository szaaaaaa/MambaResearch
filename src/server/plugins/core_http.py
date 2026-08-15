"""将现有 HTTP 路由和核心进程资源接入 Mamba Kernel。"""

from __future__ import annotations

from fastapi import APIRouter

from src.server.kernel.contracts import AsyncDisposer, KernelContext, PluginManifest
from src.server.projects.db import get_db, init_mamba_db
from src.server.projects.registry import sync_active_project_env
from src.server.routes.auth import router as auth_router
from src.server.routes.claude_code import router as claude_code_router
from src.server.routes.cli_providers import router as cli_providers_router
from src.server.routes.codex import router as codex_router
from src.server.routes.config import router as config_router
from src.server.routes.conversation_switch import router as conversation_switch_router
from src.server.routes.conversations import router as conversations_router
from src.server.routes.history_runs import router as history_runs_router
from src.server.routes.library import router as library_router
from src.server.routes.literature import router as literature_router
from src.server.routes.mcp_calls import router as mcp_calls_router
from src.server.routes.mcp_servers import router as mcp_servers_router
from src.server.routes.models import router as model_router
from src.server.routes.project_config import router as project_config_router
from src.server.routes.projects import router as projects_router
from src.server.routes.skills import router as skills_router
from src.server.routes.terminal import router as terminal_router
from src.server.routes.workspace import router as workspace_router

router = APIRouter()
for _router in (
    model_router,
    config_router,
    projects_router,
    project_config_router,
    workspace_router,
    auth_router,
    conversations_router,
    conversation_switch_router,
    skills_router,
    claude_code_router,
    cli_providers_router,
    codex_router,
    mcp_servers_router,
    mcp_calls_router,
    literature_router,
    library_router,
    history_runs_router,
    terminal_router,
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
        try:
            sync_active_project_env()
        except BaseException:
            get_db().close()
            raise

        async def dispose() -> None:
            get_db().close()

        return dispose
