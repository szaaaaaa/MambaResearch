"""Subagent 定义加载器（Task 3）。

**背景**：``ClaudeAgentOptions.setting_sources=["user"]`` 会让 CLI 只加载 user 层
settings（``~/.claude/settings.json``），跳过 ``project`` 层——这是 Workbench 有意为
之（见 session_manager ``_build_client`` 注释：跳过项目 settings 的 allow-list，
强制 HITL can_use_tool 桥生效）。副作用是 CLI 不会自动发现项目 ``.claude/agents/``
下的 subagent 定义。DP1 的 fallback：改走程序化注入 ``ClaudeAgentOptions.agents``。

本模块在启动期读取 ``<repo_root>/.claude/agents/*.md``，把 frontmatter + body 解析
为 ``dict[str, AgentDefinition]``，供 ``_build_client`` 注入每个 session。

文件格式（单一事实源）：

    ---
    name: paper-searcher
    description: ...
    model: haiku
    tools:
      - Read
      - WebSearch
    mcpServers:
      - search
      - paper_search
    ---
    System prompt body (markdown, multi-line).

**严格模式**：frontmatter 缺失或必填字段（name/description）为空 → 启动期显式抛
``AgentDefinitionError``，不静默忽略。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from claude_agent_sdk import AgentDefinition

__all__ = [
    "AgentDefinitionError",
    "load_subagents_from_directory",
]


class AgentDefinitionError(ValueError):
    """subagent 定义文件解析失败——格式错、缺必填字段、name 冲突等皆用此异常。"""


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)


def _parse_one(path: Path) -> tuple[str, AgentDefinition]:
    """解析单个 .md → ``(name, AgentDefinition)``。"""
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise AgentDefinitionError(
            f"{path.name}: missing YAML frontmatter "
            "(file must start with '---\\n...\\n---\\n')"
        )
    raw_frontmatter, body = match.groups()
    try:
        front = yaml.safe_load(raw_frontmatter) or {}
    except yaml.YAMLError as exc:
        raise AgentDefinitionError(
            f"{path.name}: frontmatter YAML parse error: {exc}"
        ) from exc
    if not isinstance(front, dict):
        raise AgentDefinitionError(
            f"{path.name}: frontmatter must be a mapping, got "
            f"{type(front).__name__}"
        )

    name = front.get("name")
    if not isinstance(name, str) or not name.strip():
        raise AgentDefinitionError(
            f"{path.name}: frontmatter must include non-empty 'name'"
        )
    description = front.get("description")
    if not isinstance(description, str) or not description.strip():
        raise AgentDefinitionError(
            f"{path.name}: frontmatter must include non-empty 'description'"
        )

    prompt = body.strip()
    if not prompt:
        raise AgentDefinitionError(
            f"{path.name}: body (system prompt) must not be empty"
        )

    # 可选字段——缺省即 None / 空列表
    model = front.get("model")
    if model is not None and not isinstance(model, str):
        raise AgentDefinitionError(
            f"{path.name}: 'model' must be a string alias or full id, got "
            f"{type(model).__name__}"
        )

    tools = _parse_string_list(front.get("tools"), path.name, "tools")
    mcp_servers_raw = front.get("mcpServers")
    mcp_servers = _parse_mcp_servers(mcp_servers_raw, path.name)

    return name.strip(), AgentDefinition(
        description=description.strip(),
        prompt=prompt,
        tools=tools,
        model=model,
        mcpServers=mcp_servers,
    )


def _parse_string_list(
    value: Any, file_name: str, field: str
) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise AgentDefinitionError(
            f"{file_name}: '{field}' must be a list, got {type(value).__name__}"
        )
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise AgentDefinitionError(
                f"{file_name}: '{field}' entries must be non-empty strings, "
                f"got {item!r}"
            )
        out.append(item.strip())
    return out


def _parse_mcp_servers(
    value: Any, file_name: str
) -> list[str | dict[str, Any]] | None:
    """mcpServers 允许 list[str] 或 list[str | inline dict]。"""
    if value is None:
        return None
    if not isinstance(value, list):
        raise AgentDefinitionError(
            f"{file_name}: 'mcpServers' must be a list, got "
            f"{type(value).__name__}"
        )
    out: list[str | dict[str, Any]] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            out.append(item)
        else:
            raise AgentDefinitionError(
                f"{file_name}: 'mcpServers' entries must be strings or "
                f"inline mappings, got {item!r}"
            )
    return out


def load_subagents_from_directory(
    directory: Path,
) -> dict[str, AgentDefinition]:
    """扫描目录里全部 ``*.md`` 并解析。

    Parameters
    ----------
    directory : Path
        通常是 ``<repo_root>/.claude/agents``。目录不存在直接返回空 dict——
        首次启动 / 新 checkout 场景允许。

    Returns
    -------
    dict[str, AgentDefinition]
        以 frontmatter 的 ``name`` 为键。同 name 冲突 → 抛 AgentDefinitionError。
    """
    if not directory.exists() or not directory.is_dir():
        return {}
    registry: dict[str, AgentDefinition] = {}
    for path in sorted(directory.glob("*.md")):
        name, definition = _parse_one(path)
        if name in registry:
            raise AgentDefinitionError(
                f"duplicate agent name {name!r} "
                f"(second occurrence in {path.name})"
            )
        registry[name] = definition
    return registry
