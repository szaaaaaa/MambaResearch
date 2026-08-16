"""Research MCP plugin wiring。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from src.server.integrations.colab.mcp_server import (
    default_mcp_config as colab_mcp_config,
)
from src.server.integrations.experiment.mcp_server import (
    default_mcp_config as experiment_mcp_config,
)
from src.server.integrations.mamba_history.mcp_server import (
    default_mcp_config as history_mcp_config,
)
from src.server.integrations.paper_search.mcp_server import (
    default_mcp_config as paper_search_mcp_config,
)
from src.server.integrations.zotero.mcp_server import (
    default_mcp_config as zotero_mcp_config,
)
from src.server.kernel.contracts import (
    AsyncDisposer,
    KernelContext,
    McpStdioConfig,
    PluginManifest,
)
from src.server.routes.library import router as library_router
from src.server.routes.workspace import router as workspace_router
from src.server.workspace.mcp_server import default_mcp_config as workspace_mcp_config


_REPO_ROOT = Path(__file__).resolve().parents[3]
McpConfigBuilder = Callable[[Path], dict[str, dict[str, Any]]]


@dataclass(frozen=True)
class _DefaultMcpProvider:
    id: str
    label: str
    config_builder: McpConfigBuilder

    def resolve_config(self) -> McpStdioConfig:
        configs = self.config_builder(_REPO_ROOT)
        if not isinstance(configs, dict) or set(configs) != {self.id}:
            raise ValueError(f"MCP provider {self.id} returned an invalid server mapping")
        raw = configs[self.id]
        if not isinstance(raw, dict) or raw.get("type") != "stdio":
            raise ValueError(f"MCP provider {self.id} must return a stdio configuration")
        command = raw.get("command")
        args = raw.get("args")
        env = raw.get("env")
        if not isinstance(command, str) or not command.strip():
            raise ValueError(f"MCP provider {self.id} returned an invalid command")
        if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
            raise ValueError(f"MCP provider {self.id} returned invalid args")
        if not isinstance(env, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in env.items()
        ):
            raise ValueError(f"MCP provider {self.id} returned invalid env")
        return McpStdioConfig(command=command, args=tuple(args), env=dict(env))


class ResearchPlugin:
    def __init__(
        self,
        *,
        plugin_id: str,
        provider: _DefaultMcpProvider,
        router: APIRouter | None = None,
    ) -> None:
        self.manifest = PluginManifest(id=plugin_id)
        self._provider = provider
        self._router = router

    def register(self, context: KernelContext) -> None:
        context.plugin_config(self.manifest.id)
        context.capabilities.mcp.register(
            plugin_id=self.manifest.id,
            provider=self._provider,
        )
        if self._router is not None:
            context.capabilities.http.register(
                contribution_id=self.manifest.id,
                plugin_id=self.manifest.id,
                router=self._router,
            )

    async def start(self, context: KernelContext) -> AsyncDisposer | None:
        return None


def builtin_research_plugins() -> tuple[ResearchPlugin, ...]:
    return (
        ResearchPlugin(
            plugin_id="research.workspace",
            provider=_DefaultMcpProvider(
                id="mamba_workspace",
                label="Workspace",
                config_builder=workspace_mcp_config,
            ),
            router=workspace_router,
        ),
        ResearchPlugin(
            plugin_id="research.zotero",
            provider=_DefaultMcpProvider(
                id="mamba_zotero",
                label="Zotero",
                config_builder=zotero_mcp_config,
            ),
            router=library_router,
        ),
        ResearchPlugin(
            plugin_id="research.experiment",
            provider=_DefaultMcpProvider(
                id="mamba_experiment",
                label="Experiment",
                config_builder=experiment_mcp_config,
            ),
        ),
        ResearchPlugin(
            plugin_id="research.paper_search",
            provider=_DefaultMcpProvider(
                id="paper_search",
                label="Paper Search",
                config_builder=paper_search_mcp_config,
            ),
        ),
        ResearchPlugin(
            plugin_id="research.colab",
            provider=_DefaultMcpProvider(
                id="mamba_colab",
                label="Colab",
                config_builder=colab_mcp_config,
            ),
        ),
        ResearchPlugin(
            plugin_id="research.mamba_history",
            provider=_DefaultMcpProvider(
                id="mamba_history",
                label="Mamba History",
                config_builder=history_mcp_config,
            ),
        ),
    )
