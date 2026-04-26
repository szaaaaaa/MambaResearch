"""Subagent 定义加载器测试（Task 3）。

覆盖 acceptance：
1. 5 个文件各有完整 YAML frontmatter（name / description / model / tools / mcpServers）
2. 模型分配符合 plan（paper-searcher/evidence-extractor → haiku；
   analyzer/writer → sonnet；critic → opus）
3. DP1 fallback：`_build_client` 把加载好的 agents 注入 options.agents，
   不依赖 setting_sources
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import src.server.claude_code.session_manager as sm_module
from src.server.claude_code.agents import (
    AgentDefinitionError,
    load_subagents_from_directory,
)
from src.server.settings import ROOT


REPO_AGENTS = ROOT / ".claude" / "agents"


# ---------------------------------------------------------------------------
# AC1/AC2: 5 个文件 + 模型分配
# ---------------------------------------------------------------------------


def test_repo_defines_eight_subagents():
    """确认 repo 下 .claude/agents/ 有且只有 v3 Stage 5 要求的 8 个文件。"""
    registry = load_subagents_from_directory(REPO_AGENTS)
    assert set(registry.keys()) == {
        "paper-searcher",
        "evidence-extractor",
        "analyzer",
        "writer",
        "critic",
        "conductor",
        "experimenter",
        "reviewer",
    }


@pytest.mark.parametrize(
    "name,expected_model",
    [
        ("paper-searcher", "haiku"),
        ("evidence-extractor", "haiku"),
        ("analyzer", "sonnet"),
        ("writer", "sonnet"),
        ("critic", "opus"),
        ("conductor", "sonnet"),
        ("experimenter", "sonnet"),
        ("reviewer", "sonnet"),
    ],
)
def test_model_assignment_uses_aliases(name: str, expected_model: str):
    """模型字段应为别名而非完整 ID；分配符合 plan 的分档。"""
    registry = load_subagents_from_directory(REPO_AGENTS)
    assert registry[name].model == expected_model


def test_every_agent_has_required_frontmatter_fields():
    """每个 agent 都应有 description / tools / mcpServers（tools/mcpServers 允许为 None
    但不能是"字段名拼错或缺失"——用非空检查代替）。"""
    registry = load_subagents_from_directory(REPO_AGENTS)
    for name, definition in registry.items():
        assert definition.description, f"{name}: missing description"
        assert definition.prompt.strip(), f"{name}: empty system prompt body"
        # tools 与 mcpServers 允许 None（subagent 可以不挂工具），但仓库里的 5 个
        # 都显式配了——做一次反回归
        assert definition.tools is not None, f"{name}: tools missing"
        assert definition.mcpServers is not None, f"{name}: mcpServers missing"


# ---------------------------------------------------------------------------
# 加载器严格性
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_missing_frontmatter_raises(tmp_path):
    _write(tmp_path / "bad.md", "No frontmatter here, just body.")
    with pytest.raises(AgentDefinitionError, match="missing YAML frontmatter"):
        load_subagents_from_directory(tmp_path)


def test_missing_name_raises(tmp_path):
    _write(
        tmp_path / "bad.md",
        "---\ndescription: x\n---\nbody",
    )
    with pytest.raises(AgentDefinitionError, match="non-empty 'name'"):
        load_subagents_from_directory(tmp_path)


def test_missing_description_raises(tmp_path):
    _write(
        tmp_path / "bad.md",
        "---\nname: foo\n---\nbody",
    )
    with pytest.raises(AgentDefinitionError, match="non-empty 'description'"):
        load_subagents_from_directory(tmp_path)


def test_empty_body_raises(tmp_path):
    _write(
        tmp_path / "bad.md",
        "---\nname: foo\ndescription: x\n---\n   \n",
    )
    with pytest.raises(AgentDefinitionError, match="body.*must not be empty"):
        load_subagents_from_directory(tmp_path)


def test_tools_wrong_type_raises(tmp_path):
    _write(
        tmp_path / "bad.md",
        "---\nname: foo\ndescription: x\ntools: Read\n---\nbody",
    )
    with pytest.raises(AgentDefinitionError, match="'tools' must be a list"):
        load_subagents_from_directory(tmp_path)


def test_duplicate_names_raise(tmp_path):
    _write(
        tmp_path / "a.md",
        "---\nname: same\ndescription: x\n---\nbody",
    )
    _write(
        tmp_path / "b.md",
        "---\nname: same\ndescription: y\n---\nbody",
    )
    with pytest.raises(AgentDefinitionError, match="duplicate agent name"):
        load_subagents_from_directory(tmp_path)


def test_nonexistent_directory_returns_empty(tmp_path):
    assert load_subagents_from_directory(tmp_path / "does-not-exist") == {}


# ---------------------------------------------------------------------------
# AC3: _build_client 注入 options.agents（DP1 fallback 真实落地）
# ---------------------------------------------------------------------------


class _Capture:
    """捕获 options 的假 SDK client。"""

    captured_options = None

    def __init__(self, options):
        _Capture.captured_options = options

    async def connect(self):
        pass

    async def disconnect(self):
        pass


def test_build_client_injects_agents_into_options(monkeypatch, tmp_path):
    """_build_client 应把加载到的 subagents 塞进 options.agents——dict 按 name 索引，
    每个 value 是 AgentDefinition 实例。"""
    # 替换 SDK 客户端为捕获器
    monkeypatch.setattr(sm_module, "ClaudeSDKClient", _Capture)
    # 重置 subagent 缓存——用 repo 里的真实 5 个
    monkeypatch.setattr(sm_module, "_cached_subagents", None)

    async def run():
        await sm_module._build_client(
            session_id="test-session",
            cwd=str(tmp_path),
            model=None,
            permission_mode="default",
            add_dirs=[],
            permission_state=sm_module.PermissionState(),
            options_overrides=None,
            sdk_resume=False,
        )

    asyncio.run(run())

    opts = _Capture.captured_options
    assert opts is not None
    # options 是 ClaudeAgentOptions 实例——取 agents 字段
    agents = getattr(opts, "agents", None)
    assert agents is not None, "options.agents should be injected"
    assert set(agents.keys()) == {
        "paper-searcher",
        "evidence-extractor",
        "analyzer",
        "writer",
        "critic",
        "conductor",
        "experimenter",
        "reviewer",
    }
    # setting_sources 仍为 ["user"]——DP1 的前提，不该被 fallback 改掉
    assert getattr(opts, "setting_sources", None) == ["user"]


def test_build_client_skips_agents_when_dir_empty(monkeypatch, tmp_path):
    """subagent 目录为空时 options 不带 agents 字段（不硬塞空 dict）。"""
    monkeypatch.setattr(sm_module, "ClaudeSDKClient", _Capture)
    # 指向空目录 + 强制缓存失效
    monkeypatch.setattr(sm_module, "_cached_subagents", {})
    _Capture.captured_options = None

    async def run():
        await sm_module._build_client(
            session_id="test-session",
            cwd=str(tmp_path),
            model=None,
            permission_mode="default",
            add_dirs=[],
            permission_state=sm_module.PermissionState(),
            options_overrides=None,
            sdk_resume=False,
        )

    asyncio.run(run())

    opts = _Capture.captured_options
    assert getattr(opts, "agents", None) is None
