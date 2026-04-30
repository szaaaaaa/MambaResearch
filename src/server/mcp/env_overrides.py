"""User 层 MCP env 覆盖加载器。

设计动机
~~~~~~~~

D+E 重构后 builtin helpers（``src/server/integrations/*/mcp_server.py:
default_mcp_config``）是 server 定义的程序级源——它们 hardcode 启动命令和
env keys 列表。但 paper_search 这种第三方 MCP 需要 API keys 这种**用户敏感
配置**，不能写在 git 管的代码里，也不该让 user 通过 PATCH 改 command/args
（安全边界）。

所以引入这个轻量加载器：

* settings UI 只能 PATCH 写 ``configs/mcp/env_overrides.json``
* builtin helper 在生成 ``default_mcp_config`` 时合并这个文件
* server 定义（command/args）继续硬编码在 helper 代码里——user PATCH 改不动

文件格式
~~~~~~~~

``configs/mcp/env_overrides.json``::

    {
      "paper_search": {
        "PAPER_SEARCH_MCP_CORE_API_KEY": "...",
        "PAPER_SEARCH_MCP_UNPAYWALL_EMAIL": "..."
      },
      "<other_server_id>": {
        ...
      }
    }

文件不存在 / 解析失败 / 缺指定 server_id → 静默返回空 dict。MCP server 在
缺 key 时自己处理"该数据源不可用"，不需要 hard-fail。
"""

from __future__ import annotations

import json
from pathlib import Path

# 仓库根（src/server/mcp/env_overrides.py → ../../../）
_REPO_ROOT = Path(__file__).resolve().parents[3]
_OVERRIDES_PATH = _REPO_ROOT / "configs" / "mcp" / "env_overrides.json"


def load_env_overrides(server_id: str) -> dict[str, str]:
    """读 ``configs/mcp/env_overrides.json`` 中指定 server 的 env 覆盖。

    Parameters
    ----------
    server_id : str
        MCP server 的注册 id（与 builtin helper ``default_mcp_config`` 返回字典
        的 key 一致），例如 ``paper_search``。

    Returns
    -------
    dict[str, str]
        env key → user override value 的映射。文件不存在或无该 server 段时返回
        空 dict——调用方应该把它合并到 helper 的默认 env 模板里，user 值覆盖默认。
    """
    if not _OVERRIDES_PATH.exists():
        return {}
    try:
        with _OVERRIDES_PATH.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    server_section = payload.get(server_id)
    if not isinstance(server_section, dict):
        return {}
    # 只接受字符串值——env 字段的契约是 dict[str, str]
    return {str(k): str(v) for k, v in server_section.items() if isinstance(v, (str, int, float))}
