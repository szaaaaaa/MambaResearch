"""Mamba Kernel 的 typed capability registries。"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

from src.server.kernel.contracts import (
    DuplicateCapabilityError,
    McpServerProvider,
    TerminalBackend,
    UnknownCapabilityError,
    validate_plugin_id,
)


@dataclass(frozen=True)
class HttpContribution:
    id: str
    plugin_id: str
    router: APIRouter


class HttpRegistry:
    def __init__(self) -> None:
        self._contributions: dict[str, HttpContribution] = {}

    def register(
        self,
        *,
        contribution_id: str,
        plugin_id: str,
        router: APIRouter,
    ) -> None:
        validate_plugin_id(contribution_id)
        validate_plugin_id(plugin_id)
        if contribution_id in self._contributions:
            raise DuplicateCapabilityError(
                f"HTTP contribution already registered: {contribution_id}"
            )
        self._contributions[contribution_id] = HttpContribution(
            id=contribution_id,
            plugin_id=plugin_id,
            router=router,
        )

    def list(self) -> tuple[HttpContribution, ...]:
        return tuple(self._contributions.values())


class BackendRegistry:
    def __init__(self) -> None:
        self._backends: dict[str, TerminalBackend] = {}

    def register(self, *, plugin_id: str, backend: TerminalBackend) -> None:
        validate_plugin_id(plugin_id)
        backend_id = validate_plugin_id(backend.descriptor.id)
        if backend_id in self._backends:
            raise DuplicateCapabilityError(f"backend already registered: {backend_id}")
        self._backends[backend_id] = backend

    def require(self, backend_id: str) -> TerminalBackend:
        backend = self._backends.get(backend_id)
        if backend is None:
            available = ", ".join(self._backends) or "<none>"
            raise UnknownCapabilityError(
                f"unknown backend {backend_id!r}; available: {available}"
            )
        return backend

    def list(self) -> tuple[TerminalBackend, ...]:
        return tuple(self._backends.values())


class McpRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, McpServerProvider] = {}

    def register(self, *, plugin_id: str, provider: McpServerProvider) -> None:
        validate_plugin_id(plugin_id)
        server_id = validate_plugin_id(provider.id)
        if server_id in self._providers:
            raise DuplicateCapabilityError(
                f"MCP server already registered: {server_id}"
            )
        self._providers[server_id] = provider

    def require(self, server_id: str) -> McpServerProvider:
        provider = self._providers.get(server_id)
        if provider is None:
            available = ", ".join(self._providers) or "<none>"
            raise UnknownCapabilityError(
                f"unknown MCP server {server_id!r}; available: {available}"
            )
        return provider

    def list(self) -> tuple[McpServerProvider, ...]:
        return tuple(self._providers.values())


class CapabilityRegistry:
    def __init__(self) -> None:
        self.http = HttpRegistry()
        self.backends = BackendRegistry()
        self.mcp = McpRegistry()
