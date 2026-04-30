"""paper_search MCP server 配置适配层。

本模块**不实现** MCP server 本体——它在 PyPI 包 ``paper_search_mcp`` 里，通过
``python -m paper_search_mcp.server`` 启动。本仓库只需要告诉 registry：

* server 名字叫 ``paper_search``
* 启动命令 = ``sys.executable -m paper_search_mcp.server``
* 接受哪些 env keys（API keys 列表）
* env 实际值从 ``configs/mcp/env_overrides.json`` 的 user override 层读取

这种"程序级 server 定义 + user 级 env override"的两层结构来自 D+E 重构的设计
约束：用户能通过 settings UI 改 API key（env），但**不能**改启动命令——server
定义在 git 管的代码里，不会被 PATCH 写到任何 user-editable 文件。

env keys 列表
~~~~~~~~~~~~~

下列 keys 是 ``paper_search_mcp`` 上游约定的可选凭证；缺省全为空字符串，
表示"不启用对应数据源"（ ``paper_search_mcp`` 自己处理"key 不存在则跳过该
data source"）：

- ``PAPER_SEARCH_MCP_UNPAYWALL_EMAIL``
- ``PAPER_SEARCH_MCP_CORE_API_KEY``
- ``PAPER_SEARCH_MCP_SEMANTIC_SCHOLAR_API_KEY``
- ``PAPER_SEARCH_MCP_ZENODO_ACCESS_TOKEN``
- ``PAPER_SEARCH_MCP_DOAJ_API_KEY``
- ``PAPER_SEARCH_MCP_GOOGLE_SCHOLAR_PROXY_URL``
- ``PAPER_SEARCH_MCP_IEEE_API_KEY``
- ``PAPER_SEARCH_MCP_ACM_API_KEY``
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from src.server.mcp.env_overrides import load_env_overrides

SERVER_ID = "paper_search"

# 已知 env keys —— 默认值留空，user override 后注入子进程。
# 列出"接受的 keys 清单"对 settings UI 渲染编辑表单是必要的。
KNOWN_ENV_KEYS: tuple[str, ...] = (
    "PAPER_SEARCH_MCP_UNPAYWALL_EMAIL",
    "PAPER_SEARCH_MCP_CORE_API_KEY",
    "PAPER_SEARCH_MCP_SEMANTIC_SCHOLAR_API_KEY",
    "PAPER_SEARCH_MCP_ZENODO_ACCESS_TOKEN",
    "PAPER_SEARCH_MCP_DOAJ_API_KEY",
    "PAPER_SEARCH_MCP_GOOGLE_SCHOLAR_PROXY_URL",
    "PAPER_SEARCH_MCP_IEEE_API_KEY",
    "PAPER_SEARCH_MCP_ACM_API_KEY",
)


def default_mcp_config(root: Path) -> dict[str, dict[str, Any]]:
    """返回供 Claude Agent SDK ``mcp_servers`` 用的默认配置。

    与 ``workspace.mcp_server.default_mcp_config`` 同形式：返回
    ``{server_name: {type, command, args, env}}``。session_manager 把所有
    builtin helper 的 dict 合并后传给 ``ClaudeAgentOptions``。

    env 字段 = 已知 keys 模板（全空字符串）∪ user override（``configs/mcp/
    env_overrides.json`` 中 ``paper_search`` 段）。后者覆盖前者。

    ``root`` 参数当前未使用，但保持与其他 helper 同构签名，便于 registry 统一调用。
    """
    base_env: dict[str, str] = {key: "" for key in KNOWN_ENV_KEYS}
    user_env = load_env_overrides(SERVER_ID)
    merged_env = {**base_env, **user_env}
    return {
        SERVER_ID: {
            "type": "stdio",
            "command": sys.executable,
            "args": ["-m", "paper_search_mcp.server"],
            "env": merged_env,
        },
    }
