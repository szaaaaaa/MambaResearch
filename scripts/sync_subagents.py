"""Subagent 单一源同步工具（Task 5a）。

将 ``.claude/agents/*.md`` （YAML frontmatter + markdown body，Claude 侧 subagent
定义的单一事实源）转换为 ``.codex/agents/*.toml``，供 Workbench 的 Codex session
manager（Task 5b/5c）作为 developer instructions 注入给 ``codex app-server``。

**为什么要 converter 而不是让 Codex 直接读 .md？**

Codex CLI 本身没有和 Claude Code subagent 等价的"子 agent 定义"机制（`codex
--help` 下没有 `agents` 子命令）。我们把 ResearchAgent 自己的 Codex session 后端
用 TOML 格式读入 subagent 定义，所以需要一个机械化的转换步骤，让 `.claude` 那
边改动自动同步到 `.codex` 那边——避免人工双写。

**字段映射**：

============ ================================= ===========================
Source (.md) Target (.toml)                    备注
============ ================================= ===========================
name         name                              scalar string
description  description                       scalar string
model        model = "gpt-5.5"                 硬编码（plan 决定：Codex 侧
                                                不做 haiku/sonnet/opus 分档）
tools        (not emitted)                     used only to derive sandbox_mode
mcpServers   (not emitted)                     used only to derive sandbox_mode
(derived)    sandbox_mode                      derived from mcpServers / tools
body         developer_instructions            multi-line string
============ ================================= ===========================

**sandbox_mode 推导规则**（忠于"写操作需要 workspace-write 权限"的直觉）：

- 含 ``exec`` mcp server（本仓的 exec 即 shell 执行能力），或
- 含 ``Bash / Write / Edit / NotebookEdit`` 任一 tool

→ ``workspace-write``，否则 ``read-only``。

**严格模式**：frontmatter 缺失 / 字段非法 → 抛 ``AgentDefinitionError``。沿用
``src.server.claude_code.agents`` 的解析器，保持与运行时同一份语义。

CLI 用法
--------
默认运行（相对于 repo 根）::

    python scripts/sync_subagents.py

自定义路径::

    python scripts/sync_subagents.py --src .claude/agents --dst .codex/agents
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomli_w

# 复用运行时加载器——保证 parser 语义完全一致（单一源的单一解析器）。
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.server.claude_code.agents import (  # noqa: E402
    AgentDefinitionError,
    _parse_one,
)

__all__ = [
    "CODEX_MODEL",
    "ConvertedAgent",
    "convert_agent",
    "main",
    "sync_directory",
]


CODEX_MODEL = "gpt-5.5"
"""Codex 侧统一用 gpt-5.5（见 plan 决策：不做模型分档）。"""

_WRITE_TOOLS = frozenset({"Bash", "Write", "Edit", "NotebookEdit"})
_WRITE_MCP = frozenset({"exec"})


@dataclass(frozen=True)
class ConvertedAgent:
    """转换后的单条 agent 配置，字段顺序决定 TOML 写盘顺序。"""

    name: str
    description: str
    model: str
    tools: list[str]
    mcp_servers: list[str]
    sandbox_mode: str
    developer_instructions: str

    def to_toml_dict(self) -> dict[str, Any]:
        """按 TOML 写盘顺序返回 dict（保持字段顺序稳定）。"""
        return {
            "name": self.name,
            "description": self.description,
            "model": self.model,
            "sandbox_mode": self.sandbox_mode,
            "developer_instructions": self.developer_instructions,
        }


def _derive_sandbox_mode(
    tools: list[str] | None,
    mcp_servers: list[str | dict[str, Any]] | None,
) -> str:
    """从 tools + mcpServers 推导 sandbox_mode。"""
    # mcpServers 条目可能是 str 也可能是 inline dict（带 server_id 键）
    mcp_names: set[str] = set()
    for entry in mcp_servers or []:
        if isinstance(entry, str):
            mcp_names.add(entry)
        elif isinstance(entry, dict):
            # inline dict 一般长这样 {"server_id": "...", "command": [...]}
            sid = entry.get("server_id") or entry.get("name")
            if isinstance(sid, str):
                mcp_names.add(sid)
    tool_names = set(tools or [])
    if tool_names & _WRITE_TOOLS or mcp_names & _WRITE_MCP:
        return "workspace-write"
    return "read-only"


def _mcp_servers_as_strings(
    mcp_servers: list[str | dict[str, Any]] | None,
) -> list[str]:
    """把 mcpServers 统一为字符串列表——inline dict 取 server_id。"""
    if not mcp_servers:
        return []
    out: list[str] = []
    for entry in mcp_servers:
        if isinstance(entry, str):
            out.append(entry)
        elif isinstance(entry, dict):
            sid = entry.get("server_id") or entry.get("name")
            if isinstance(sid, str):
                out.append(sid)
            else:
                raise AgentDefinitionError(
                    f"mcpServers inline dict must contain 'server_id' or "
                    f"'name' as string, got {entry!r}"
                )
    return out


def convert_agent(path: Path) -> ConvertedAgent:
    """解析单个 .md 并转换为 ``ConvertedAgent``。

    Parameters
    ----------
    path : Path
        ``.claude/agents/<name>.md`` 的路径。

    Returns
    -------
    ConvertedAgent
        可直接写 TOML 的结构化条目。

    Raises
    ------
    AgentDefinitionError
        当 .md 格式错误、缺字段、或 mcpServers inline dict 非法时抛出。
    """
    name, definition = _parse_one(path)
    mcp_strs = _mcp_servers_as_strings(definition.mcpServers)
    sandbox = _derive_sandbox_mode(definition.tools, definition.mcpServers)
    return ConvertedAgent(
        name=name,
        description=definition.description,
        model=CODEX_MODEL,
        tools=list(definition.tools or []),
        mcp_servers=mcp_strs,
        sandbox_mode=sandbox,
        developer_instructions=definition.prompt,
    )


_HEADER_TEMPLATE = """\
# Auto-generated from .claude/agents/{stem}.md by scripts/sync_subagents.py.
# DO NOT EDIT — change the .md source and re-run the converter.

"""


def _write_toml(agent: ConvertedAgent, dst: Path, stem: str) -> None:
    """把 converted agent 写入目标 TOML 文件，带 header 提示。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    payload = tomli_w.dumps(agent.to_toml_dict())
    dst.write_text(
        _HEADER_TEMPLATE.format(stem=stem) + payload,
        encoding="utf-8",
        newline="\n",
    )


def sync_directory(src_dir: Path, dst_dir: Path) -> list[Path]:
    """扫描 ``src_dir`` 下所有 ``*.md`` 并转换写入 ``dst_dir``。

    Parameters
    ----------
    src_dir : Path
        源目录（通常为 ``.claude/agents``）。不存在或空目录 → 返回空列表，
        不抛异常（首次 checkout / 暂无 subagent 的工程允许）。
    dst_dir : Path
        目标目录（通常为 ``.codex/agents``）。会自动创建。

    Returns
    -------
    list[Path]
        成功写盘的 .toml 文件路径列表（按 stem 字典序）。

    Raises
    ------
    AgentDefinitionError
        任一 .md 格式错误或转换失败时抛出；已写盘的前序文件会保留（fail-fast，
        不做 rollback——用户重跑即可）。
    """
    if not src_dir.exists() or not src_dir.is_dir():
        return []
    written: list[Path] = []
    for md_path in sorted(src_dir.glob("*.md")):
        agent = convert_agent(md_path)
        dst_path = dst_dir / f"{md_path.stem}.toml"
        _write_toml(agent, dst_path, md_path.stem)
        written.append(dst_path)
    return written


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert .claude/agents/*.md → .codex/agents/*.toml. "
            "Claude subagents are the single source of truth; this keeps "
            "Codex copies in sync."
        )
    )
    parser.add_argument(
        "--src",
        type=Path,
        default=_REPO_ROOT / ".claude" / "agents",
        help="source dir (default: <repo>/.claude/agents)",
    )
    parser.add_argument(
        "--dst",
        type=Path,
        default=_REPO_ROOT / ".codex" / "agents",
        help="destination dir (default: <repo>/.codex/agents)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress per-file output on success",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        written = sync_directory(args.src, args.dst)
    except AgentDefinitionError as exc:
        print(f"sync_subagents: FAIL — {exc}", file=sys.stderr)
        return 1
    if not args.quiet:
        if not written:
            print(f"sync_subagents: no agents found under {args.src}")
        else:
            print(f"sync_subagents: wrote {len(written)} file(s) to {args.dst}")
            for path in written:
                print(f"  - {path.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
