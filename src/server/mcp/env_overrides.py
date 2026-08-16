"""User 层 MCP env 覆盖加载器。

设计动机
~~~~~~~~

D+E 重构后 Research plugin 独占调用的 ``default_mcp_config`` 是 server 定义的
程序级源——它们 hardcode 启动命令和
env keys 列表。但 paper_search 这种第三方 MCP 需要 API keys 这种**用户敏感
配置**，不能写在 git 管的代码里，也不该让 user 通过 PATCH 改 command/args
（安全边界）。

所以引入这个轻量加载器：

* settings UI 只能 PATCH 写 ``configs/mcp/env_overrides.json``
* Research plugin 在解析 ``default_mcp_config`` 时合并这个文件
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


def _read_all_overrides() -> dict[str, dict[str, str]]:
    """读整个 env_overrides.json 返回 ``{server_id: {key: value}}``——内部工具。

    文件不存在 / JSON 错误 / 顶层非 dict → 返回空 dict。本函数对 caller 隐藏所有
    "文件可能损坏"的细节：load 视角永远拿到一个有效 dict。
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
    result: dict[str, dict[str, str]] = {}
    for sid, section in payload.items():
        if not isinstance(sid, str) or not isinstance(section, dict):
            continue
        result[sid] = {
            str(k): str(v)
            for k, v in section.items()
            if isinstance(v, (str, int, float))
        }
    return result


def load_env_overrides(server_id: str) -> dict[str, str]:
    """读 ``configs/mcp/env_overrides.json`` 中指定 server 的 env 覆盖。

    Parameters
    ----------
    server_id : str
        MCP server 的注册 id（与所属 Research plugin 调用的 ``default_mcp_config`` 返回字典
        的 key 一致），例如 ``paper_search``。

    Returns
    -------
    dict[str, str]
        env key → user override value 的映射。文件不存在或无该 server 段时返回
        空 dict——调用方应该把它合并到 helper 的默认 env 模板里，user 值覆盖默认。
    """
    return _read_all_overrides().get(server_id, {})


def write_env_overrides(server_id: str, env: dict[str, str]) -> dict[str, str]:
    """覆盖写指定 server 的 env override 字典，返回写入后的值。

    settings UI PATCH 端点的目的端——只能改 env 字段，**不能**改 command/args
    （那些在 Research plugin 的 server-local 构造器里硬编码）。本函数：

    1. 读现有 env_overrides.json（不存在视为空）
    2. 把 ``server_id`` 段整段替换成 ``env``
    3. 写回（保证父目录存在、UTF-8、indent=2）

    Parameters
    ----------
    server_id : str
        MCP server id。
    env : dict[str, str]
        新的 env 字典；空 dict 表示"清空该 server 的 override"。所有非字符串值
        被强制转 str（与 ``load_env_overrides`` 的契约对齐）。

    Returns
    -------
    dict[str, str]
        实际写入磁盘的 env 字典（即字符串化后的 ``env``）。
    """
    sanitized: dict[str, str] = {str(k): str(v) for k, v in env.items()}
    all_overrides = _read_all_overrides()
    if sanitized:
        all_overrides[server_id] = sanitized
    else:
        all_overrides.pop(server_id, None)
    _OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _OVERRIDES_PATH.open("w", encoding="utf-8") as fp:
        json.dump(all_overrides, fp, indent=2, ensure_ascii=False, sort_keys=False)
        fp.write("\n")
    return sanitized
