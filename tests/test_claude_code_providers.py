"""Provider registry 加载器测试。

覆盖 acceptance：
1. registry 文件存在且合法 → 正确解析为 ProviderConfig，可按 name 索引
2. 文件 / 注册表缺失 → 返回空 dict（"未配置"场景非错误）
3. 字段缺失或类型错误 → 启动期显式 raise ProviderRegistryError
"""
from __future__ import annotations

import json

import pytest

from src.server.claude_code.providers import (
    ProviderConfig,
    ProviderRegistryError,
    load_provider_registry,
)
from src.server.settings import CLAUDE_CODE_PROVIDERS_PATH


# ---------------------------------------------------------------------------
# AC1 & AC2: parses real providers.json + indexes by name
# ---------------------------------------------------------------------------


def test_load_from_real_providers_json_has_anthropic():
    """配置文件里声明的 anthropic 条目应被正确解析。"""
    with CLAUDE_CODE_PROVIDERS_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    registry = load_provider_registry(raw)
    assert "anthropic" in registry
    entry = registry["anthropic"]
    assert isinstance(entry, ProviderConfig)
    assert entry.name == "anthropic"
    assert entry.base_url.startswith("https://")
    assert entry.api_key_env == "ANTHROPIC_API_KEY"


def test_multi_provider_indexed_by_name():
    raw = {
        "anthropic": {
            "base_url": "https://api.anthropic.com",
            "api_key_env": "ANTHROPIC_API_KEY",
            "default_model": "",
        },
        "deepseek": {
            "base_url": "http://localhost:3456",
            "api_key_env": "ANTHROPIC_API_KEY",
            "default_model": "deepseek-chat",
        },
    }
    reg = load_provider_registry(raw)
    assert set(reg.keys()) == {"anthropic", "deepseek"}
    assert reg["deepseek"].default_model == "deepseek-chat"
    assert reg["deepseek"].base_url == "http://localhost:3456"


# ---------------------------------------------------------------------------
# AC2: missing / non-dict input returns empty registry (not an error)
# ---------------------------------------------------------------------------


def test_missing_returns_empty():
    assert load_provider_registry({}) == {}


def test_none_input_returns_empty():
    # 文件不存在等场景 caller 传 None，应返回空 registry 而非炸
    assert load_provider_registry(None) == {}  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC3: malformed input raises ProviderRegistryError (not silent)
# ---------------------------------------------------------------------------


def test_top_level_not_mapping_raises():
    with pytest.raises(ProviderRegistryError, match="must be a mapping"):
        load_provider_registry(["anthropic"])  # type: ignore[arg-type]


def test_entry_missing_required_field_raises():
    raw = {
        "broken": {
            "base_url": "https://x",
            "api_key_env": "KEY",
            # default_model 缺失
        }
    }
    with pytest.raises(ProviderRegistryError, match="missing required field"):
        load_provider_registry(raw)


def test_entry_wrong_type_field_raises():
    raw = {
        "broken": {
            "base_url": 42,  # 非 str
            "api_key_env": "KEY",
            "default_model": "",
        }
    }
    with pytest.raises(ProviderRegistryError, match="must be a string"):
        load_provider_registry(raw)


def test_entry_not_mapping_raises():
    raw = {"broken": "not-a-dict"}
    with pytest.raises(ProviderRegistryError, match="entry must be a mapping"):
        load_provider_registry(raw)


def test_empty_provider_name_raises():
    raw = {
        "": {
            "base_url": "x",
            "api_key_env": "K",
            "default_model": "",
        }
    }
    with pytest.raises(ProviderRegistryError, match="non-empty string"):
        load_provider_registry(raw)
