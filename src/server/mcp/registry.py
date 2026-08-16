"""MCP server registry——多 source 整合。

Source 优先级与去重
~~~~~~~~~~~~~~~~~~~
按 server ``name`` 去重；多个 source 撞同一 name 时：

* ``transport`` / ``command`` / ``args`` / ``env`` / ``url``：以最先注册的 source 为准
  （顺序：mamba_managed → codex_project → codex_global → mcp_json）
* ``sources`` / ``config_paths``：累加列表，UI 展示"这个 server 在哪些来源里都被引用了"

``.mcp.json`` 只服务 MCP 控制台的自定义 server；Codex 自身仍按原生配置规则读取
user 和 active-project 配置。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.server.kernel.contracts import McpServerProvider
from src.server.mcp.models import McpServerInfo, SourceLabel, Transport


# 仓库根（src/server/mcp/registry.py → ../../../）
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _normalize_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _normalize_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def _normalize_env(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    return {}


def _detect_transport(raw: dict[str, Any]) -> Transport:
    """从 config 字段推断 transport：``type`` 字段优先，其次按是否有 url 兜底。

    Claude SDK 的 mcp_servers 配置约定：``type='stdio'/'http'/'sse'``。
    Codex CLI 的 .toml 段未必带 type 字段——但本仓库目前所有 server 都是 stdio，
    这里默认 stdio 是安全的；后续 http/sse server 接入时手动加 ``type=http``。
    """
    t = _normalize_str(raw.get("type"))
    if t in ("stdio", "http", "sse"):
        return t  # type: ignore[return-value]
    if _normalize_str(raw.get("url")):
        return "http"
    return "stdio"


def _build_server(
    name: str,
    raw: dict[str, Any],
    *,
    source: SourceLabel,
    config_path: str,
) -> McpServerInfo:
    return McpServerInfo(
        name=name,
        transport=_detect_transport(raw),
        sources=[source],
        config_paths=[config_path],
        command=_normalize_str(raw.get("command")),
        args=_normalize_str_list(raw.get("args")),
        env=_normalize_env(raw.get("env")),
        url=_normalize_str(raw.get("url")),
    )


def _merge_into(
    target: dict[str, McpServerInfo],
    new: McpServerInfo,
) -> None:
    """新条目 → 已存在则只追加 sources/config_paths，否则插入。

    通过先注册的 source 决定真实命令——后注册的 source 仅做"被引用"标记。
    """
    existing = target.get(new.name)
    if existing is None:
        target[new.name] = new
        return
    for src in new.sources:
        if src not in existing.sources:
            existing.sources.append(src)
    for cp in new.config_paths:
        if cp not in existing.config_paths:
            existing.config_paths.append(cp)


# ---------------------------------------------------------------------------
# Source readers
# ---------------------------------------------------------------------------


def _read_mamba_managed(
    providers: tuple[McpServerProvider, ...],
) -> list[McpServerInfo]:
    items: list[McpServerInfo] = []
    for provider in providers:
        config = provider.resolve_config()
        items.append(
            McpServerInfo(
                name=provider.id,
                transport="stdio",
                sources=["mamba_managed"],
                config_paths=["<kernel>"],
                command=config.command,
                args=list(config.args),
                env=dict(config.env),
            )
        )
    return items


def _read_toml_mcp_servers(
    path: Path, *, source: SourceLabel
) -> list[McpServerInfo]:
    """解析一个 .codex/config.toml，提取 ``[mcp_servers.*]`` 段。

    用 stdlib ``tomllib``（Python 3.11+，本项目 baseline 已是 3.11）。文件不存在 / 解析
    失败时静默返回空 —— UI 上 "无该 source" 比 "整个 registry 崩溃" 更友好。
    """
    if not path.exists():
        return []
    try:
        import tomllib  # 3.11+
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    section = data.get("mcp_servers") or {}
    if not isinstance(section, dict):
        return []
    items: list[McpServerInfo] = []
    for name, raw in section.items():
        if not isinstance(raw, dict):
            continue
        items.append(
            _build_server(name, raw, source=source, config_path=str(path))
        )
    return items


def _read_mcp_json(path: Path) -> list[McpServerInfo]:
    """解析 MCP 控制台使用的 .mcp.json。

    Schema：
    ``{"mcpServers": {"<name>": {"type":..., "command":..., "args":[...], "env":{...}}}}``

    Mamba-managed server 由 Kernel 注入，用户自定义 server 继续由此文件提供。
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    section = data.get("mcpServers") or {}
    if not isinstance(section, dict):
        return []
    items: list[McpServerInfo] = []
    for name, raw in section.items():
        if not isinstance(raw, dict):
            continue
        items.append(
            _build_server(name, raw, source="mcp_json", config_path=str(path))
        )
    return items


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_servers(
    managed_providers: tuple[McpServerProvider, ...],
    *,
    repo_root: Path | None = None,
    project_root: Path | None = None,
    codex_home: Path | None = None,
) -> list[McpServerInfo]:
    """聚合所有 source，返回去重后的 server 列表。

    Parameters
    ----------
    repo_root : Path or None
        MCP 控制台 ``.mcp.json`` 所在的仓库根。测试可注入临时目录。
    project_root : Path or None
        active research project 根，用于读取该项目的 Codex 原生配置。
    codex_home : Path or None
        Codex 全局 config 所在目录（``~/.codex``）。测试时可指向 tmp。
    """
    root = repo_root or _REPO_ROOT
    codex_dir = codex_home or (Path.home() / ".codex")

    aggregated: dict[str, McpServerInfo] = {}

    # 顺序敏感——先注册的 source 决定 command/args/env 的"权威值"
    for srv in _read_mamba_managed(managed_providers):
        _merge_into(aggregated, srv)
    if project_root is not None:
        for srv in _read_toml_mcp_servers(
            project_root / ".codex" / "config.toml", source="codex_project"
        ):
            _merge_into(aggregated, srv)
    for srv in _read_toml_mcp_servers(
        codex_dir / "config.toml", source="codex_global"
    ):
        _merge_into(aggregated, srv)
    for srv in _read_mcp_json(root / ".mcp.json"):
        _merge_into(aggregated, srv)

    return list(aggregated.values())


def get_server(
    name: str,
    managed_providers: tuple[McpServerProvider, ...],
    *,
    repo_root: Path | None = None,
    project_root: Path | None = None,
    codex_home: Path | None = None,
) -> McpServerInfo | None:
    for srv in list_servers(
        managed_providers,
        repo_root=repo_root,
        project_root=project_root,
        codex_home=codex_home,
    ):
        if srv.name == name:
            return srv
    return None
