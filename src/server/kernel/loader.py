"""Profile 解析、catalog 校验、依赖排序和纯注册。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from src.server.kernel.contracts import (
    DuplicatePluginError,
    InvalidProfileError,
    KernelConfig,
    KernelContext,
    KernelSnapshot,
    MissingPluginDependencyError,
    Plugin,
    PluginConfig,
    PluginDependencyCycleError,
    PluginManifest,
    UnknownPluginError,
    validate_plugin_id,
)
from src.server.kernel.registry import CapabilityRegistry


@dataclass(frozen=True)
class LoadedKernel:
    config: KernelConfig
    context: KernelContext
    plugins: tuple[Plugin, ...]

    def snapshot(self) -> KernelSnapshot:
        return KernelSnapshot(api_version=1, enabled_plugins=self.config.plugin_ids)


def load_kernel(
    *,
    profile_path: Path,
    catalog: Iterable[Plugin],
) -> LoadedKernel:
    """加载 profile，校验 catalog/依赖，并执行无副作用注册。"""
    profile_name, profile_ids, plugin_configs = _load_profile(profile_path)
    catalog_by_id = _build_catalog(catalog)
    selected_plugins = _select_plugins(profile_ids, catalog_by_id)
    ordered_plugins = _resolve_dependencies(selected_plugins)
    config = KernelConfig(
        profile=profile_name,
        plugin_ids=tuple(plugin.manifest.id for plugin in ordered_plugins),
        plugins={
            plugin_id: plugin_configs[plugin_id]
            for plugin_id in (plugin.manifest.id for plugin in ordered_plugins)
        },
    )
    context = KernelContext(config=config, capabilities=CapabilityRegistry())
    for plugin in ordered_plugins:
        plugin.register(context)
    return LoadedKernel(
        config=config,
        context=context,
        plugins=tuple(ordered_plugins),
    )


def _load_profile(profile_path: Path) -> tuple[str, tuple[str, ...], dict[str, PluginConfig]]:
    try:
        raw = profile_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvalidProfileError(f"cannot read plugin profile {profile_path}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidProfileError(f"invalid plugin profile JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise InvalidProfileError("plugin profile must be a JSON object")

    _require_exact_keys(payload, {"profile", "plugins"}, "plugin profile")
    profile_name = payload["profile"]
    plugin_entries = payload["plugins"]
    if not isinstance(profile_name, str) or not profile_name.strip():
        raise InvalidProfileError("plugin profile name must be a non-empty string")
    if not isinstance(plugin_entries, list):
        raise InvalidProfileError("plugin profile plugins must be a list")

    plugin_ids: list[str] = []
    plugin_configs: dict[str, PluginConfig] = {}
    for entry in plugin_entries:
        if not isinstance(entry, dict):
            raise InvalidProfileError("plugin profile entries must be objects")
        _require_exact_keys(entry, {"id", "config"}, "plugin profile entry")
        plugin_id = entry.get("id")
        validate_plugin_id(plugin_id)
        if plugin_id in plugin_configs:
            raise DuplicatePluginError(f"plugin profile contains duplicate ID: {plugin_id}")
        config = entry.get("config", {})
        if not isinstance(config, dict):
            raise InvalidProfileError(f"plugin config for {plugin_id} must be an object")
        plugin_ids.append(plugin_id)
        plugin_configs[plugin_id] = PluginConfig(values=dict(config))

    return profile_name, tuple(plugin_ids), plugin_configs


def _require_exact_keys(
    payload: dict[str, Any],
    allowed: set[str],
    label: str,
) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise InvalidProfileError(f"{label} contains unknown fields: {sorted(unknown)}")
    missing = allowed - set(payload)
    if missing == {"config"}:
        return
    if missing:
        raise InvalidProfileError(f"{label} is missing required fields: {sorted(missing)}")


def _build_catalog(catalog: Iterable[Plugin]) -> dict[str, Plugin]:
    catalog_by_id: dict[str, Plugin] = {}
    for plugin in catalog:
        manifest = getattr(plugin, "manifest", None)
        if not isinstance(manifest, PluginManifest):
            raise InvalidProfileError("catalog plugin must expose a PluginManifest")
        if not callable(getattr(plugin, "register", None)):
            raise InvalidProfileError(f"catalog plugin {manifest.id} has no register()")
        if not callable(getattr(plugin, "start", None)):
            raise InvalidProfileError(f"catalog plugin {manifest.id} has no start()")
        if manifest.id in catalog_by_id:
            raise DuplicatePluginError(f"plugin catalog contains duplicate ID: {manifest.id}")
        catalog_by_id[manifest.id] = plugin
    return catalog_by_id


def _select_plugins(
    profile_ids: tuple[str, ...],
    catalog_by_id: dict[str, Plugin],
) -> tuple[Plugin, ...]:
    selected: list[Plugin] = []
    for plugin_id in profile_ids:
        plugin = catalog_by_id.get(plugin_id)
        if plugin is None:
            raise UnknownPluginError(f"plugin profile references unknown ID: {plugin_id}")
        selected.append(plugin)
    return tuple(selected)


def _resolve_dependencies(selected_plugins: tuple[Plugin, ...]) -> tuple[Plugin, ...]:
    enabled_by_id = {plugin.manifest.id: plugin for plugin in selected_plugins}
    states: dict[str, str] = {}
    stack: list[str] = []
    ordered: list[Plugin] = []

    def visit(plugin_id: str) -> None:
        state = states.get(plugin_id)
        if state == "visited":
            return
        if state == "visiting":
            cycle_start = stack.index(plugin_id)
            cycle = stack[cycle_start:] + [plugin_id]
            raise PluginDependencyCycleError(
                f"plugin dependency cycle: {' -> '.join(cycle)}"
            )

        plugin = enabled_by_id[plugin_id]
        states[plugin_id] = "visiting"
        stack.append(plugin_id)
        for dependency_id in plugin.manifest.requires:
            if dependency_id not in enabled_by_id:
                raise MissingPluginDependencyError(
                    f"plugin {plugin_id} requires disabled plugin {dependency_id}"
                )
            visit(dependency_id)
        stack.pop()
        states[plugin_id] = "visited"
        ordered.append(plugin)

    for plugin in selected_plugins:
        visit(plugin.manifest.id)
    return tuple(ordered)
