"""Subagent 同步脚本测试（Task 5a）。

覆盖 acceptance criteria：

1. 真实 5 份 ``.claude/agents/*.md`` → 生成 5 份 ``.codex/agents/*.toml``，
   且与仓库已 commit 的产物字节一致（保证脚本是幂等 + 同步正确的）。
2. 字段映射正确（name / description / model=gpt-5.5 / tools / mcp_servers /
   sandbox_mode 派生规则 / developer_instructions=body）。
3. 源目录为空或不存在 → 返回空列表，不报错。
4. frontmatter 缺 name（非法） → 抛 ``AgentDefinitionError``。
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

from src.server.claude_code.agents import AgentDefinitionError
from src.server.settings import ROOT

# 让 scripts/ 能像包一样 import——converter 脚本在 scripts/ 根层。
_SCRIPTS = ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import sync_subagents  # noqa: E402


_REPO_CLAUDE = ROOT / ".claude" / "agents"
_REPO_CODEX = ROOT / ".codex" / "agents"
_EXPECTED_NAMES = {
    "analyzer",
    "conductor",
    "critic",
    "evidence-extractor",
    "experimenter",
    "paper-searcher",
    "reviewer",
    "writer",
}


# ---------------------------------------------------------------------------
# AC1：5 输入 → 5 输出，且与仓库 committed 产物一致
# ---------------------------------------------------------------------------


def test_converter_produces_expected_eight_files(tmp_path: Path):
    """源目录 8 个 .md 跑 converter → 恰好生成 8 个 .toml。"""
    dst = tmp_path / "codex_agents"
    written = sync_subagents.sync_directory(_REPO_CLAUDE, dst)
    assert len(written) == 8
    assert {p.stem for p in written} == _EXPECTED_NAMES
    assert {p.name for p in dst.glob("*.toml")} == {
        f"{n}.toml" for n in _EXPECTED_NAMES
    }


def test_repo_codex_agents_in_sync_with_claude_sources(tmp_path: Path):
    """仓库 committed 的 .codex/agents/*.toml 必须与 .claude 源一致。

    相当于一个 drift detector——有人改了 .md 忘了跑 converter 提交会在这里挂掉。
    """
    dst = tmp_path / "codex_agents"
    sync_subagents.sync_directory(_REPO_CLAUDE, dst)
    for name in _EXPECTED_NAMES:
        fresh = (dst / f"{name}.toml").read_text(encoding="utf-8")
        committed = (_REPO_CODEX / f"{name}.toml").read_text(encoding="utf-8")
        assert fresh == committed, (
            f".codex/agents/{name}.toml out of sync with .claude source — "
            "run `python scripts/sync_subagents.py` and commit the changes"
        )


# ---------------------------------------------------------------------------
# AC2：字段映射正确
# ---------------------------------------------------------------------------


def _load_toml(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def test_field_mapping_paper_searcher_readonly(tmp_path: Path):
    """paper-searcher：无 exec / 无写工具 → read-only；保留原 mcp_servers。"""
    dst = tmp_path / "out"
    sync_subagents.sync_directory(_REPO_CLAUDE, dst)
    data = _load_toml(dst / "paper-searcher.toml")
    assert data["name"] == "paper-searcher"
    assert data["model"] == "gpt-5.5"
    assert data["sandbox_mode"] == "read-only"
    assert data["tools"] == ["Read", "WebSearch", "WebFetch", "Grep", "Glob"]
    assert data["mcp_servers"] == ["search", "paper_search"]
    # developer_instructions 是从 markdown body 透传的非空字符串
    assert isinstance(data["developer_instructions"], str)
    assert "论文搜索专员" in data["developer_instructions"]
    assert data["description"].startswith("学术论文搜索专员")


def test_field_mapping_analyzer_workspace_write(tmp_path: Path):
    """analyzer：含 exec MCP 且有 Write/Edit/Bash → workspace-write。"""
    dst = tmp_path / "out"
    sync_subagents.sync_directory(_REPO_CLAUDE, dst)
    data = _load_toml(dst / "analyzer.toml")
    assert data["name"] == "analyzer"
    assert data["model"] == "gpt-5.5"
    assert data["sandbox_mode"] == "workspace-write"
    assert set(data["tools"]) >= {"Write", "Edit", "Bash"}
    assert "exec" in data["mcp_servers"]


def test_field_mapping_writer_workspace_write_via_tools(tmp_path: Path):
    """writer：无 exec MCP 但有 Write/Edit → workspace-write（tools-driven）。"""
    dst = tmp_path / "out"
    sync_subagents.sync_directory(_REPO_CLAUDE, dst)
    data = _load_toml(dst / "writer.toml")
    assert data["sandbox_mode"] == "workspace-write"
    assert "exec" not in data["mcp_servers"]
    assert {"Write", "Edit"} <= set(data["tools"])


def test_all_toml_are_valid_and_have_required_keys(tmp_path: Path):
    """每个生成的 TOML 都可解析，且 7 个必填字段齐全。"""
    dst = tmp_path / "out"
    sync_subagents.sync_directory(_REPO_CLAUDE, dst)
    required = {
        "name",
        "description",
        "model",
        "tools",
        "mcp_servers",
        "sandbox_mode",
        "developer_instructions",
    }
    for name in _EXPECTED_NAMES:
        data = _load_toml(dst / f"{name}.toml")
        assert required <= data.keys(), (
            f"{name}.toml missing keys: {required - data.keys()}"
        )
        assert data["model"] == "gpt-5.5"  # 一律 gpt-5.5


# ---------------------------------------------------------------------------
# AC3：空目录 / 缺席目录
# ---------------------------------------------------------------------------


def test_empty_source_dir_returns_nothing(tmp_path: Path):
    """源目录存在但无 .md → 空列表，不创建 output 文件。"""
    src = tmp_path / "empty"
    src.mkdir()
    dst = tmp_path / "out"
    written = sync_subagents.sync_directory(src, dst)
    assert written == []
    # 目录未创建（因为没东西可写）也算通过——宽松检查即可
    assert not any(dst.glob("*.toml")) if dst.exists() else True


def test_missing_source_dir_returns_nothing(tmp_path: Path):
    """源目录不存在 → 空列表，不报错。"""
    src = tmp_path / "does_not_exist"
    dst = tmp_path / "out"
    written = sync_subagents.sync_directory(src, dst)
    assert written == []


# ---------------------------------------------------------------------------
# AC4：格式错误抛显式异常
# ---------------------------------------------------------------------------


def test_missing_name_raises_explicit_error(tmp_path: Path):
    """frontmatter 缺 name → AgentDefinitionError 显式抛出。"""
    src = tmp_path / "bad"
    src.mkdir()
    bad_md = src / "broken.md"
    bad_md.write_text(
        "---\ndescription: no name here\n---\nbody text.\n",
        encoding="utf-8",
    )
    dst = tmp_path / "out"
    with pytest.raises(AgentDefinitionError, match="name"):
        sync_subagents.sync_directory(src, dst)


def test_missing_frontmatter_raises_explicit_error(tmp_path: Path):
    """.md 完全没有 YAML frontmatter → AgentDefinitionError。"""
    src = tmp_path / "bad"
    src.mkdir()
    (src / "naked.md").write_text("just body, no frontmatter.\n", encoding="utf-8")
    with pytest.raises(AgentDefinitionError, match="frontmatter"):
        sync_subagents.sync_directory(src, tmp_path / "out")


# ---------------------------------------------------------------------------
# CLI 入口 smoke
# ---------------------------------------------------------------------------


def test_cli_main_returns_zero_on_success(tmp_path: Path, capsys):
    """sync_subagents.main() 成功时返回 0；失败时返回 1。"""
    rc = sync_subagents.main(
        [
            "--src",
            str(_REPO_CLAUDE),
            "--dst",
            str(tmp_path / "cli_out"),
            "--quiet",
        ]
    )
    assert rc == 0
    assert (tmp_path / "cli_out").is_dir()


def test_cli_main_returns_one_on_parse_error(tmp_path: Path, capsys):
    src = tmp_path / "bad"
    src.mkdir()
    (src / "x.md").write_text("no frontmatter.\n", encoding="utf-8")
    rc = sync_subagents.main(
        [
            "--src",
            str(src),
            "--dst",
            str(tmp_path / "out"),
            "--quiet",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "FAIL" in err
