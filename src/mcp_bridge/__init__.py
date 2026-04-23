"""ResearchAgent MCP 桥——把内置 skills 暴露为 stdio MCP 工具。

包含两个子模块：

- ``invoker``：把 MCP ``tools/call`` 的 JSON 参数合成 ``ArtifactRecord`` 列表、
  构造 ``SkillContext`` 并调度 skill 运行；另提供 ``build_tool_descriptor``
  从 ``skill.yaml`` + ``skill.md`` 生成 MCP 工具 schema。
- ``server``：stdio JSON-RPC 主循环；``python -m src.mcp_bridge.server``
  作为独立进程启动，供 Claude Agent SDK 通过 ``mcp_servers`` 挂载。

暴露粒度：一个 skill 对应一个 MCP tool，tool name 为 ``<skill_id>``；
Claude Agent SDK 在宿主侧会自动前缀为 ``mcp__research_agent__<skill_id>``。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from src.mcp_bridge.invoker import (
    EXPOSED_SKILLS,
    build_tool_descriptor,
    invoke_skill,
)

# session_manager 默认挂载的 MCP server 名——对应 Claude 视角的 mcp__research_agent__*
DEFAULT_SERVER_NAME = "research_agent"


def default_mcp_config(root: Path) -> dict[str, dict[str, Any]]:
    """返回 Claude Agent SDK ``mcp_servers`` 默认配置——挂载本桥。

    约定
    ----
    - ``command`` 使用当前进程的 ``sys.executable``：确保 subprocess 与主后端
      使用同一个 Python 解释器（避免 venv 切换把 ``claude_agent_sdk`` 不可导入
      的版本拉起来）
    - ``args`` 指向 ``python -m src.mcp_bridge.server``，并把 ``--root`` 显式
      透传，便于跨工作目录启动（默认值是仓库根，不是父进程 ``cwd``）
    - ``PYTHONPATH`` 注入仓库根，保证子进程能 import ``src.*``
    - 允许通过环境变量 ``RESEARCH_AGENT_MCP_DISABLED=1`` 整体关闭（返回空 dict）

    Parameters
    ----------
    root : Path
        仓库根路径；配置里的 ``cwd`` / ``--root`` 都指向它。

    Returns
    -------
    dict[str, dict]
        形如 ``{"research_agent": {"command": ..., "args": [...], ...}}``；
        可直接透传到 ``ClaudeAgentOptions.mcp_servers``。
    """
    if os.environ.get("RESEARCH_AGENT_MCP_DISABLED", "").strip() == "1":
        return {}
    resolved_root = str(root.resolve())
    env = {"PYTHONPATH": resolved_root}
    return {
        DEFAULT_SERVER_NAME: {
            "type": "stdio",
            "command": sys.executable,
            "args": [
                "-m",
                "src.mcp_bridge.server",
                "--root",
                resolved_root,
            ],
            "env": env,
        },
    }


__all__ = [
    "DEFAULT_SERVER_NAME",
    "EXPOSED_SKILLS",
    "build_tool_descriptor",
    "default_mcp_config",
    "invoke_skill",
]
