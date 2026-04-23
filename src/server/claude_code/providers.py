"""Claude Code provider registry 加载器。

``configs/agent.yaml`` 的 ``claude_code.providers`` 段列出 Workbench 可用的 LLM
provider（Anthropic 原生 / claude-code-router 反代 / OpenRouter 等）。本模块
负责把该段解析为 ``dict[str, ProviderConfig]``，供 session 创建路径按名查表、
以及 ``GET /api/claude-code/providers`` 端点列举。

**严格模式**：registry 段存在但字段缺失或类型错误 → 启动期显式 raise
``ProviderRegistryError``，绝不静默忽略。段缺失视为"未配置"，返回空字典——
此时 1b/1c 的"未传 provider 即 Anthropic 默认行为"路径仍可工作。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "ProviderConfig",
    "ProviderRegistryError",
    "load_provider_registry",
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


def load_provider_registry(cfg: dict[str, Any]) -> dict[str, ProviderConfig]:
    """从已加载的 agent.yaml 字典解析 provider registry。

    Parameters
    ----------
    cfg : dict
        ``yaml.safe_load`` 后的完整配置字典。本函数只读 ``claude_code.providers``
        一段，其它字段不触碰。

    Returns
    -------
    dict[str, ProviderConfig]
        以 name 为键的不可变配置表；段缺失返回空 dict。

    Raises
    ------
    ProviderRegistryError
        registry 段不是 dict、任一 entry 不是 dict、任一必填字段缺失或非字符串。
    """
    claude_code = cfg.get("claude_code") if isinstance(cfg, dict) else None
    if claude_code is None:
        return {}
    if not isinstance(claude_code, dict):
        raise ProviderRegistryError(
            f"`claude_code` must be a mapping, got {type(claude_code).__name__}"
        )
    raw = claude_code.get("providers")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ProviderRegistryError(
            f"`claude_code.providers` must be a mapping, got {type(raw).__name__}"
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
