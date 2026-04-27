"""MCP server 配置文件读写（Stage 3 Task 4）。

支持的 source（写）
~~~~~~~~~~~~~~~~~~
- ``.mcp.json``（项目级，Claude Code 约定的 ``mcpServers`` 段）

不支持写的 source
~~~~~~~~~~~~~~~~~
- ``builtin_helper``：programmatic config，由 Python 代码维护，不可由 UI 修改
- ``.codex/config.toml`` / ``~/.codex/config.toml``：含有非 mcp_servers 段（profile /
  其它配置），TOML 写入需要保留注释 + 其它段，复杂度大于价值。用户当前接入新
  server 的标准路径是写 ``.mcp.json``——Claude 与 Codex 都能识别（Codex 通过附加
  CLI 标志或镜像配置），后续若必须支持 codex_global 写入再扩展

设计要点
~~~~~~~~
- 原子写：``write_text(tmp) + os.replace`` 防破坏
- 同 server name 已存在：POST 走 409；DELETE 不存在走 404
- builtin server name 受保护：POST 创建同名抛 409，DELETE 抛 403
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[3]


class McpConfigError(Exception):
    """配置文件 IO / 校验错误的基类。"""


class McpConfigConflict(McpConfigError):
    """同名 server 已存在（写）/ 不存在（删）。"""


class McpConfigForbidden(McpConfigError):
    """目标 server 是 builtin、不可改。"""


# 不可被 .mcp.json 覆盖的 builtin server name
_BUILTIN_NAMES: frozenset[str] = frozenset({"mamba_workspace"})


def _mcp_json_path(repo_root: Path | None = None) -> Path:
    return (repo_root or _REPO_ROOT) / ".mcp.json"


def _load_mcp_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"mcpServers": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise McpConfigError(f".mcp.json 损坏（{path}）：{exc}") from exc
    if not isinstance(data, dict):
        raise McpConfigError(f".mcp.json 顶层必须是对象（{path}）")
    if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
        data["mcpServers"] = {}
    return data


def _save_mcp_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _validate_server_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """规范化用户提交的 server 配置。

    - ``name`` 必填；不含空白
    - ``transport`` ∈ {stdio, http, sse}
    - stdio 必须有 ``command``；http/sse 必须有 ``url``
    - ``args`` 缺省 []；``env`` 缺省 {}
    """
    name = str(payload.get("name") or "").strip()
    if not name:
        raise McpConfigError("name 必填")
    if any(c.isspace() for c in name):
        raise McpConfigError("name 不能含空白字符")

    transport = (payload.get("transport") or "stdio").strip()
    if transport not in {"stdio", "http", "sse"}:
        raise McpConfigError(f"transport 必须是 stdio / http / sse 之一，收到 {transport!r}")

    body: dict[str, Any] = {"type": transport}
    if transport == "stdio":
        command = str(payload.get("command") or "").strip()
        if not command:
            raise McpConfigError("stdio server 必须给 command")
        body["command"] = command
        args = payload.get("args") or []
        if not isinstance(args, list) or any(not isinstance(a, str) for a in args):
            raise McpConfigError("args 必须是字符串数组")
        body["args"] = list(args)
    else:
        url = str(payload.get("url") or "").strip()
        if not url:
            raise McpConfigError(f"{transport} server 必须给 url")
        body["url"] = url

    env = payload.get("env") or {}
    if not isinstance(env, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()
    ):
        raise McpConfigError("env 必须是 string→string 的对象")
    if env:
        body["env"] = dict(env)

    return {"name": name, "body": body}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def list_custom_servers(repo_root: Path | None = None) -> dict[str, dict[str, Any]]:
    """读 .mcp.json 的 ``mcpServers`` 段（不含 builtin / codex toml）。"""
    return dict(_load_mcp_json(_mcp_json_path(repo_root)).get("mcpServers") or {})


def add_custom_server(
    payload: dict[str, Any],
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """新增 server 到 .mcp.json。

    Raises
    ------
    McpConfigError
        body 校验失败。
    McpConfigConflict
        ``name`` 已存在于 .mcp.json。
    McpConfigForbidden
        ``name`` 与 builtin server 重名。
    """
    norm = _validate_server_payload(payload)
    name = norm["name"]
    if name in _BUILTIN_NAMES:
        raise McpConfigForbidden(
            f"{name!r} 是 MambaResearch builtin server，不能用 .mcp.json 覆盖。"
        )
    path = _mcp_json_path(repo_root)
    data = _load_mcp_json(path)
    if name in data["mcpServers"]:
        raise McpConfigConflict(f"server {name!r} 已存在于 .mcp.json")
    data["mcpServers"][name] = norm["body"]
    _save_mcp_json(path, data)
    return {"name": name, **norm["body"]}


def delete_custom_server(
    name: str, *, repo_root: Path | None = None
) -> None:
    name = name.strip()
    if name in _BUILTIN_NAMES:
        raise McpConfigForbidden(
            f"{name!r} 是 builtin server，不能从 .mcp.json 删除。"
        )
    path = _mcp_json_path(repo_root)
    data = _load_mcp_json(path)
    if name not in data["mcpServers"]:
        raise McpConfigConflict(f"server {name!r} 不在 .mcp.json 里")
    del data["mcpServers"][name]
    _save_mcp_json(path, data)
