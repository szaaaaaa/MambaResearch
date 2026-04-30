"""Claude Code provider registry 加载器。

``configs/claude_code/providers.json`` 列出 Workbench 可用的 LLM provider
（Anthropic 原生 / claude-code-router 反代 / OpenRouter 等）。本模块负责把该
注册表解析为 ``dict[str, ProviderConfig]``，供 session 创建路径按名查表、
以及 ``GET /api/claude-code/providers`` 端点列举。

**严格模式**：注册表存在但字段缺失或类型错误 → 启动期显式 raise
``ProviderRegistryError``，绝不静默忽略。文件缺失视为"未配置"，返回空字典——
此时 "未传 provider 即 Anthropic 默认行为"路径仍可工作。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping

__all__ = [
    "ProviderConfig",
    "ProviderRegistryError",
    "build_env_for_provider",
    "get_provider_registry",
    "load_provider_registry",
    "reset_provider_registry_cache",
]


class ProviderRegistryError(ValueError):
    """registry 解析失败——字段缺失、类型错误、重复键等皆用此异常。"""


@dataclass(frozen=True)
class ProviderConfig:
    """单个 provider 的静态配置。

    Attributes
    ----------
    name : str
        registry 键名（``anthropic`` / ``deepseek`` / ``openrouter`` 等）。
    base_url : str
        LLM API 端点。Anthropic 原生填 ``https://api.anthropic.com``；走
        claude-code-router 时填本地反代 URL（如 ``http://localhost:3456``）。
    api_key_env : str
        环境变量名（不是 key 本身），session 创建时由 ``_build_client`` 解析为
        ``ANTHROPIC_API_KEY`` 注入 SDK 子进程 env。此字段从不随响应回传前端。
    default_model : str
        该 provider 下的默认模型。空串表示"让 SDK 选默认模型"。
    """

    name: str
    base_url: str
    api_key_env: str
    default_model: str


_REQUIRED_FIELDS: tuple[str, ...] = ("base_url", "api_key_env", "default_model")


def load_provider_registry(raw: Any) -> dict[str, ProviderConfig]:
    """从 providers.json 字典解析 provider registry。

    Parameters
    ----------
    raw : dict[str, dict[str, str]] or any
        来自 ``configs/claude_code/providers.json`` 的解析结果，形状为
        ``{<provider_name>: {"base_url": ..., "api_key_env": ..., "default_model": ...}}``。
        非 dict（含 ``None``）视为"未配置"，返回空 registry。

    Returns
    -------
    dict[str, ProviderConfig]
        以 name 为键的不可变配置表；输入为非 dict 时返回空 dict。

    Raises
    ------
    ProviderRegistryError
        任一 entry 不是 dict、任一必填字段缺失或非字符串、provider name 非空字符串。
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ProviderRegistryError(
            f"providers registry must be a mapping, got {type(raw).__name__}"
        )

    registry: dict[str, ProviderConfig] = {}
    for name, entry in raw.items():
        if not isinstance(name, str) or not name:
            raise ProviderRegistryError(
                f"provider name must be a non-empty string, got {name!r}"
            )
        if not isinstance(entry, dict):
            raise ProviderRegistryError(
                f"provider {name!r}: entry must be a mapping, got "
                f"{type(entry).__name__}"
            )
        kwargs: dict[str, str] = {}
        for field in _REQUIRED_FIELDS:
            if field not in entry:
                raise ProviderRegistryError(
                    f"provider {name!r}: missing required field {field!r}"
                )
            value = entry[field]
            if not isinstance(value, str):
                raise ProviderRegistryError(
                    f"provider {name!r}: field {field!r} must be a string, "
                    f"got {type(value).__name__}"
                )
            kwargs[field] = value
        registry[name] = ProviderConfig(name=name, **kwargs)
    return registry


# ---------------------------------------------------------------------------
# Runtime helpers — cached registry access & env resolution
# ---------------------------------------------------------------------------


_cached_registry: dict[str, ProviderConfig] | None = None


def get_provider_registry() -> dict[str, ProviderConfig]:
    """进程内单例 registry——按需加载 ``configs/claude_code/providers.json``。

    首次调用读文件 + 解析；之后返回缓存。配置格式错误在首次调用抛
    ``ProviderRegistryError``。需要刷新（测试替换配置）调
    ``reset_provider_registry_cache``。
    """
    global _cached_registry
    if _cached_registry is not None:
        return _cached_registry
    from src.server.settings import CLAUDE_CODE_PROVIDERS_PATH

    if not CLAUDE_CODE_PROVIDERS_PATH.exists():
        _cached_registry = {}
        return _cached_registry
    with CLAUDE_CODE_PROVIDERS_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    _cached_registry = load_provider_registry(raw)
    return _cached_registry


def reset_provider_registry_cache() -> None:
    """清掉单例缓存——测试场景替换配置后调用。"""
    global _cached_registry
    _cached_registry = None


def build_env_for_provider(
    provider: ProviderConfig, os_env: Mapping[str, str] | None = None
) -> dict[str, str]:
    """把 ``ProviderConfig`` 翻译成 SDK 子进程 env override。

    查询 ``os_env[provider.api_key_env]`` 作为实际 key 值，组装：
    ``{"ANTHROPIC_API_KEY": <key>, "ANTHROPIC_BASE_URL": provider.base_url}``。

    Parameters
    ----------
    provider : ProviderConfig
        已解析的 provider 条目。
    os_env : Mapping[str, str] or None
        环境变量源；默认 ``os.environ``。测试可注入受控字典。

    Raises
    ------
    ProviderRegistryError
        ``api_key_env`` 指向的环境变量未设置或为空——缺 key 不是可恢复状态，
        不提供默认，按 CLAUDE.md"不加 workaround 掩盖根因"直接抛。
    """
    env_src = os_env if os_env is not None else os.environ
    api_key = env_src.get(provider.api_key_env, "")
    if not api_key:
        raise ProviderRegistryError(
            f"provider {provider.name!r}: env {provider.api_key_env!r} "
            f"is unset or empty"
        )
    return {
        "ANTHROPIC_API_KEY": api_key,
        "ANTHROPIC_BASE_URL": provider.base_url,
    }
