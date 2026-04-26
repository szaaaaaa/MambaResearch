"""MCP server registry 多 source 整合测试（Stage 3 Task 1）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.server.mcp import registry
from src.server.mcp.models import McpServerInfo


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """构造一个伪 repo：含 .codex/config.toml + 可选 .mcp.json。

    builtin helpers 仍读真 _REPO_ROOT，所以测试环境会拿到真 helpers 输出
    （research_agent + mamba_workspace）。这刚好验证 helpers 与 toml 共存的去重。
    """
    (tmp_path / ".codex").mkdir()
    return tmp_path


def test_list_servers_includes_builtin_helpers(fake_repo: Path, tmp_path: Path):
    """无任何 toml/json，registry 应至少返回 builtin helpers 注册的 servers。"""
    servers = registry.list_servers(repo_root=fake_repo, codex_home=tmp_path / "codex_home")
    names = {s.name for s in servers}
    assert "research_agent" in names
    assert "mamba_workspace" in names
    assert "mamba_zotero" in names
    # builtin helper 来源标签
    for s in servers:
        assert "builtin_helper" in s.sources


def test_codex_project_toml_merges_into_existing(fake_repo: Path, tmp_path: Path):
    """`.codex/config.toml` 里的同名 server 应触发 sources 累加，不覆盖 command。"""
    _write(
        fake_repo / ".codex" / "config.toml",
        """
[mcp_servers.research_agent]
command = "python"
args = ["-m", "src.mcp_bridge.server"]

[mcp_servers.mamba_workspace]
command = "python"
args = ["-m", "src.server.workspace.mcp_server"]
""",
    )
    servers = registry.list_servers(repo_root=fake_repo, codex_home=tmp_path / "codex_home")
    by_name = {s.name: s for s in servers}
    assert "builtin_helper" in by_name["research_agent"].sources
    assert "codex_project" in by_name["research_agent"].sources
    # config_paths 也累加
    assert any(".codex" in p for p in by_name["research_agent"].config_paths)


def test_unknown_server_in_toml_added(fake_repo: Path, tmp_path: Path):
    """toml 里独立定义的 server（无 builtin helper 对应）应作为新条目出现。"""
    _write(
        fake_repo / ".codex" / "config.toml",
        """
[mcp_servers.custom_extra]
command = "node"
args = ["custom-mcp.js"]
""",
    )
    servers = registry.list_servers(repo_root=fake_repo, codex_home=tmp_path / "codex_home")
    by_name = {s.name: s for s in servers}
    assert "custom_extra" in by_name
    assert by_name["custom_extra"].command == "node"
    assert by_name["custom_extra"].args == ["custom-mcp.js"]
    assert by_name["custom_extra"].sources == ["codex_project"]


def test_codex_global_toml_merges(fake_repo: Path, tmp_path: Path):
    """`~/.codex/config.toml` 也被并入。"""
    codex_home = tmp_path / "codex_home"
    _write(
        codex_home / "config.toml",
        """
[mcp_servers.global_only]
command = "echo"
args = ["hi"]
""",
    )
    servers = registry.list_servers(repo_root=fake_repo, codex_home=codex_home)
    by_name = {s.name: s for s in servers}
    assert "global_only" in by_name
    assert by_name["global_only"].sources == ["codex_global"]


def test_mcp_json_supported_when_present(fake_repo: Path, tmp_path: Path):
    """`.mcp.json` 存在时按 mcpServers 段加入。"""
    _write(
        fake_repo / ".mcp.json",
        '{"mcpServers": {"json_only": {"command": "python", "args": ["x.py"]}}}',
    )
    servers = registry.list_servers(repo_root=fake_repo, codex_home=tmp_path / "codex_home")
    by_name = {s.name: s for s in servers}
    assert "json_only" in by_name
    assert by_name["json_only"].sources == ["mcp_json"]


def test_corrupt_toml_silently_skipped(fake_repo: Path, tmp_path: Path):
    """坏 toml 不应让整个 registry 崩溃——builtin helpers 仍可用。"""
    _write(fake_repo / ".codex" / "config.toml", "this is not [valid toml")
    servers = registry.list_servers(repo_root=fake_repo, codex_home=tmp_path / "codex_home")
    assert any(s.name == "research_agent" for s in servers)


def test_get_server_returns_none_for_missing(fake_repo: Path, tmp_path: Path):
    assert (
        registry.get_server(
            "ghost", repo_root=fake_repo, codex_home=tmp_path / "codex_home"
        )
        is None
    )


def test_get_server_returns_match(fake_repo: Path, tmp_path: Path):
    s = registry.get_server(
        "mamba_workspace", repo_root=fake_repo, codex_home=tmp_path / "codex_home"
    )
    assert isinstance(s, McpServerInfo)
    assert s.name == "mamba_workspace"
    assert s.transport == "stdio"
