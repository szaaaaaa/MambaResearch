"""Mamba Kernel 的 profile、registry 与 lifecycle 合同测试。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI

from src.server.kernel.contracts import (
    BackendDescriptor,
    DuplicateCapabilityError,
    DuplicatePluginError,
    MissingPluginDependencyError,
    PluginDependencyCycleError,
    PluginManifest,
    UnknownCapabilityError,
)
from src.server.kernel.lifecycle import build_lifespan
from src.server.kernel.loader import load_kernel
from src.server.kernel.registry import BackendRegistry, HttpRegistry


class FakePlugin:
    def __init__(
        self,
        plugin_id: str,
        events: list[str],
        *,
        requires: tuple[str, ...] = (),
        register_error: BaseException | None = None,
        start_error: BaseException | None = None,
        dispose_error: BaseException | None = None,
    ) -> None:
        self.manifest = PluginManifest(id=plugin_id, requires=requires)
        self._events = events
        self._register_error = register_error
        self._start_error = start_error
        self._dispose_error = dispose_error

    def register(self, context) -> None:
        self._events.append(f"register:{self.manifest.id}")
        if self._register_error is not None:
            raise self._register_error

    async def start(self, context):
        self._events.append(f"start:{self.manifest.id}")
        if self._start_error is not None:
            raise self._start_error

        async def dispose() -> None:
            self._events.append(f"dispose:{self.manifest.id}")
            if self._dispose_error is not None:
                raise self._dispose_error

        return dispose


@dataclass(frozen=True)
class FakeBackend:
    descriptor: BackendDescriptor


def _profile(tmp_path: Path, plugin_ids: list[str]) -> Path:
    profile_path = tmp_path / "plugins.json"
    profile_path.write_text(
        json.dumps(
            {
                "profile": "test",
                "plugins": [{"id": plugin_id} for plugin_id in plugin_ids],
            }
        ),
        encoding="utf-8",
    )
    return profile_path


def test_loader_orders_dependencies_before_profile_order(tmp_path: Path) -> None:
    events: list[str] = []
    plugin_a = FakePlugin("plugin.a", events)
    plugin_b = FakePlugin("plugin.b", events, requires=("plugin.a",))

    loaded = load_kernel(
        profile_path=_profile(tmp_path, ["plugin.b", "plugin.a"]),
        catalog=(plugin_a, plugin_b),
    )

    assert loaded.config.plugin_ids == ("plugin.a", "plugin.b")
    assert events == ["register:plugin.a", "register:plugin.b"]


def test_loader_rejects_missing_dependency_before_register(tmp_path: Path) -> None:
    events: list[str] = []
    plugin = FakePlugin("plugin.b", events, requires=("plugin.a",))

    with pytest.raises(MissingPluginDependencyError, match="plugin.b.*plugin.a"):
        load_kernel(profile_path=_profile(tmp_path, ["plugin.b"]), catalog=(plugin,))

    assert events == []


def test_loader_reports_dependency_cycle(tmp_path: Path) -> None:
    events: list[str] = []
    plugin_a = FakePlugin("plugin.a", events, requires=("plugin.b",))
    plugin_b = FakePlugin("plugin.b", events, requires=("plugin.a",))

    with pytest.raises(PluginDependencyCycleError, match="plugin.a -> plugin.b -> plugin.a"):
        load_kernel(
            profile_path=_profile(tmp_path, ["plugin.a", "plugin.b"]),
            catalog=(plugin_a, plugin_b),
        )


def test_loader_rejects_duplicate_profile_and_catalog_ids(tmp_path: Path) -> None:
    events: list[str] = []
    plugin_a = FakePlugin("plugin.a", events)
    duplicate_plugin_a = FakePlugin("plugin.a", events)

    with pytest.raises(DuplicatePluginError, match="profile"):
        load_kernel(
            profile_path=_profile(tmp_path, ["plugin.a", "plugin.a"]),
            catalog=(plugin_a,),
        )
    with pytest.raises(DuplicatePluginError, match="catalog"):
        load_kernel(
            profile_path=_profile(tmp_path, ["plugin.a"]),
            catalog=(plugin_a, duplicate_plugin_a),
        )


def test_registries_preserve_order_and_reject_duplicate_or_unknown_ids() -> None:
    http = HttpRegistry()
    router_a = APIRouter()
    router_b = APIRouter()
    http.register(contribution_id="http.a", plugin_id="plugin.a", router=router_a)
    http.register(contribution_id="http.b", plugin_id="plugin.b", router=router_b)

    assert [contribution.id for contribution in http.list()] == ["http.a", "http.b"]
    with pytest.raises(DuplicateCapabilityError):
        http.register(contribution_id="http.a", plugin_id="plugin.a", router=router_a)

    backends = BackendRegistry()
    backend = FakeBackend(
        descriptor=BackendDescriptor(
            id="codex",
            label="Codex",
            supports_resume=True,
            supports_provider_selection=False,
        )
    )
    backends.register(plugin_id="backend.codex", backend=backend)

    assert backends.require("codex") is backend
    with pytest.raises(DuplicateCapabilityError):
        backends.register(plugin_id="backend.codex-copy", backend=backend)
    with pytest.raises(UnknownCapabilityError, match="codex"):
        backends.require("missing")


def test_lifecycle_starts_and_disposes_in_reverse_order(tmp_path: Path) -> None:
    events: list[str] = []
    loaded = load_kernel(
        profile_path=_profile(tmp_path, ["plugin.a", "plugin.b"]),
        catalog=(FakePlugin("plugin.a", events), FakePlugin("plugin.b", events)),
    )
    events.clear()

    async def run() -> None:
        async with build_lifespan(loaded)(FastAPI()):
            pass

    asyncio.run(run())
    assert events == [
        "start:plugin.a",
        "start:plugin.b",
        "dispose:plugin.b",
        "dispose:plugin.a",
    ]


def test_lifecycle_rolls_back_start_failure_and_continues_disposal(tmp_path: Path) -> None:
    events: list[str] = []
    loaded = load_kernel(
        profile_path=_profile(tmp_path, ["plugin.a", "plugin.b"]),
        catalog=(
            FakePlugin("plugin.a", events, dispose_error=RuntimeError("dispose a")),
            FakePlugin("plugin.b", events, start_error=RuntimeError("start b")),
        ),
    )
    events.clear()

    async def run() -> None:
        with pytest.raises(RuntimeError, match="start b"):
            async with build_lifespan(loaded)(FastAPI()):
                pass

    asyncio.run(run())
    assert events == ["start:plugin.a", "start:plugin.b", "dispose:plugin.a"]


def test_lifecycle_runs_remaining_disposers_after_shutdown_failure(tmp_path: Path) -> None:
    events: list[str] = []
    loaded = load_kernel(
        profile_path=_profile(tmp_path, ["plugin.a", "plugin.b"]),
        catalog=(
            FakePlugin("plugin.a", events),
            FakePlugin("plugin.b", events, dispose_error=RuntimeError("dispose b")),
        ),
    )
    events.clear()

    async def run() -> None:
        with pytest.raises(RuntimeError, match="dispose b"):
            async with build_lifespan(loaded)(FastAPI()):
                pass

    asyncio.run(run())
    assert events == [
        "start:plugin.a",
        "start:plugin.b",
        "dispose:plugin.b",
        "dispose:plugin.a",
    ]


def test_register_failure_never_starts_plugins(tmp_path: Path) -> None:
    events: list[str] = []
    plugin_a = FakePlugin("plugin.a", events)
    plugin_b = FakePlugin("plugin.b", events, register_error=RuntimeError("register b"))

    with pytest.raises(RuntimeError, match="register b"):
        load_kernel(
            profile_path=_profile(tmp_path, ["plugin.a", "plugin.b"]),
            catalog=(plugin_a, plugin_b),
        )

    assert events == ["register:plugin.a", "register:plugin.b"]
