"""Mamba Kernel 的稳定合同。"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeAlias


class KernelConfigurationError(RuntimeError):
    """Kernel 配置或能力注册错误的基类。"""


class InvalidProfileError(KernelConfigurationError):
    """Profile 文件格式不合法。"""


class InvalidPluginIdError(KernelConfigurationError):
    """插件或能力 ID 不合法。"""


class DuplicatePluginError(KernelConfigurationError):
    """插件 catalog 或 profile 包含重复 ID。"""


class UnknownPluginError(KernelConfigurationError):
    """Profile 引用了 catalog 中不存在的插件。"""


class MissingPluginDependencyError(KernelConfigurationError):
    """已启用插件缺少必需依赖。"""


class PluginDependencyCycleError(KernelConfigurationError):
    """插件依赖图存在闭环。"""


class DuplicateCapabilityError(KernelConfigurationError):
    """能力 ID 被重复注册。"""


class UnknownCapabilityError(KernelConfigurationError):
    """请求了未注册的能力。"""


_PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


def validate_plugin_id(plugin_id: str) -> str:
    """校验并返回稳定的插件/能力 ID。"""
    if not isinstance(plugin_id, str) or not _PLUGIN_ID_RE.fullmatch(plugin_id):
        raise InvalidPluginIdError(f"invalid plugin ID: {plugin_id!r}")
    return plugin_id


@dataclass(frozen=True)
class PluginManifest:
    id: str
    requires: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_plugin_id(self.id)
        if not isinstance(self.requires, tuple):
            raise InvalidProfileError("plugin manifest requires must be a tuple")
        for dependency_id in self.requires:
            validate_plugin_id(dependency_id)


@dataclass(frozen=True)
class PluginConfig:
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KernelConfig:
    profile: str
    plugin_ids: tuple[str, ...]
    plugins: dict[str, PluginConfig]


@dataclass(frozen=True)
class KernelSnapshot:
    api_version: int
    enabled_plugins: tuple[str, ...]


@dataclass(frozen=True)
class BackendDescriptor:
    """Backend Registry 在 Batch 1 所需的最小身份描述。"""

    id: str

    def __post_init__(self) -> None:
        validate_plugin_id(self.id)


class TerminalBackend(Protocol):
    """可被 Backend Registry 消费的 backend 最小合同。"""

    descriptor: BackendDescriptor


AsyncDisposer: TypeAlias = Callable[[], Awaitable[None]]


class Plugin(Protocol):
    manifest: PluginManifest

    def register(self, context: "KernelContext") -> None:
        ...

    async def start(self, context: "KernelContext") -> AsyncDisposer | None:
        ...


@dataclass(frozen=True)
class KernelContext:
    config: KernelConfig
    capabilities: "CapabilityRegistry"

    def plugin_config(self, plugin_id: str) -> PluginConfig:
        return self.config.plugins[plugin_id]
