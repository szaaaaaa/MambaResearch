"""Provider registry 加载器测试（Task 1a）。

覆盖 acceptance：
1. registry 段存在且合法 → 正确解析为 ProviderConfig，可按 name 索引
2. 段缺失 → 返回空 dict（"未配置"场景非错误）
3. 字段缺失或类型错误 → 启动期显式 raise ProviderRegistryError
"""
from __future__ import annotations

import pytest
import yaml

from src.server.claude_code.providers import (
    ProviderConfig,
    ProviderRegistryError,
    load_provider_registry,
)
from src.server.settings import CONFIG_PATH


# ---------------------------------------------------------------------------
# AC1 & AC2: parses real agent.yaml + indexes by name
# ---------------------------------------------------------------------------


def test_load_from_real_agent_yaml_has_anthropic():
    """配置文件里声明的 anthropic 条目应被正确解析。"""
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    registry = load_provider_registry(cfg)
    assert "anthropic" in registry
    entry = registry["anthropic"]
    assert isinstance(entry, ProviderConfig)
    assert entry.name == "anthropic"
    assert entry.base_url.startswith("https://")
    assert entry.api_key_env == "ANTHROPIC_API_KEY"


def test_multi_provider_indexed_by_name():
    cfg = {
        "claude_code": {
            "providers": {
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
        }
    }
    reg = load_provider_registry(cfg)
    assert set(reg.keys()) == {"anthropic", "deepseek"}
    assert reg["deepseek"].default_model == "deepseek-chat"
    assert reg["deepseek"].base_url == "http://localhost:3456"


# ---------------------------------------------------------------------------
# AC2: missing section returns empty registry (not an error)
# ---------------------------------------------------------------------------


def test_missing_section_returns_empty():
    assert load_provider_registry({}) == {}
    assert load_provider_registry({"claude_code": {}}) == {}


def test_non_dict_top_level_returns_empty():
    # 非 dict 的 cfg 不该炸——调用方传空/异常结构时返回空 registry，
    # 由调用方决定是否走默认路径
    assert load_provider_registry(None) == {}  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC3: malformed input raises ProviderRegistryError (not silent)
# ---------------------------------------------------------------------------


def test_claude_code_section_not_mapping_raises():
    with pytest.raises(ProviderRegistryError, match="must be a mapping"):
        load_provider_registry({"claude_code": "oops"})


def test_providers_section_not_mapping_raises():
    with pytest.raises(ProviderRegistryError, match="must be a mapping"):
        load_provider_registry({"claude_code": {"providers": ["anthropic"]}})


def test_entry_missing_required_field_raises():
    cfg = {
        "claude_code": {
            "providers": {
                "broken": {
                    "base_url": "https://x",
                    "api_key_env": "KEY",
                    # default_model 缺失
                }
            }
        }
    }
    with pytest.raises(ProviderRegistryError, match="missing required field"):
        load_provider_registry(cfg)


def test_entry_wrong_type_field_raises():
    cfg = {
        "claude_code": {
            "providers": {
                "broken": {
                    "base_url": 42,  # 非 str
                    "api_key_env": "KEY",
                    "default_model": "",
                }
            }
        }
    }
    with pytest.raises(ProviderRegistryError, match="must be a string"):
        load_provider_registry(cfg)


def test_entry_not_mapping_raises():
    cfg = {"claude_code": {"providers": {"broken": "not-a-dict"}}}
    with pytest.raises(ProviderRegistryError, match="entry must be a mapping"):
        load_provider_registry(cfg)


def test_empty_provider_name_raises():
    cfg = {
        "claude_code": {
            "providers": {
                "": {
                    "base_url": "x",
                    "api_key_env": "K",
                    "default_model": "",
                }
            }
        }
    }
    with pytest.raises(ProviderRegistryError, match="non-empty string"):
        load_provider_registry(cfg)
