"""MCP server registry——多 source 整合（Stage 3 Task 1）。

Source 优先级与去重
~~~~~~~~~~~~~~~~~~~
按 server ``name`` 去重；多个 source 撞同一 name 时：

* ``transport`` / ``command`` / ``args`` / ``env`` / ``url``：以最先注册的 source 为准
  （顺序：builtin → codex_project → codex_global → mcp_json）。这与"builtin helper
  是程序权威源"的实际语义对齐——`.codex/config.toml` 是手维护的镜像，理论上一致；
  哪天不一致以 helper 为准，避免运行时无意识漂移
* ``sources`` / ``config_paths``：累加列表，UI 展示"这个 server 在哪些来源里都被引用了"

按设计 plan：``.mcp.json`` 在本仓库不存在（仅给 Claude Code 项目级，但本项目通过
SDK 程序化配置而不写文件）。本模块仍保留 ``.mcp.json`` 解析逻辑——若用户后续手动
新建则自动并入；不存在直接返回空，不浪费 IO。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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


def _read_builtin_helpers() -> list[McpServerInfo]:
    """读 MambaResearch 自家的 builtin MCP server helpers。

    这是 programmatic config——没有"配置文件路径"概念，``config_paths`` 标
    ``<programmatic>``。延迟 import 避免本模块被启动期 IO 拖慢。
    """
    from src.mcp_bridge import default_mcp_config as bridge_default_mcp_config
    from src.server.integrations.colab.mcp_server import (
        default_mcp_config as colab_default_mcp_config,
    )
    from src.server.integrations.zotero.mcp_server import (
        default_mcp_config as zotero_default_mcp_config,
    )
    from src.server.workspace.mcp_server import (
        default_mcp_config as workspace_default_mcp_config,
    )

    items: list[McpServerInfo] = []
    for func in (
        bridge_default_mcp_config,
        workspace_default_mcp_config,
        zotero_default_mcp_config,
        colab_default_mcp_config,
    ):
        config = func(_REPO_ROOT)
        for name, raw in config.items():
            items.append(
                _build_server(
                    name,
                    raw,
                    source="builtin_helper",
                    config_path="<programmatic>",
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
    """解析 .mcp.json（Claude Code 项目级约定）。

    Schema：
    ``{"mcpServers": {"<name>": {"type":..., "command":..., "args":[...], "env":{...}}}}``

    本仓库当前**不存在**此文件——所有 builtin server 走 programmatic 注入。保留
    parser 让用户手动新建时自动并入。
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
    *,
    repo_root: Path | None = None,
    codex_home: Path | None = None,
) -> list[McpServerInfo]:
    """聚合所有 source，返回去重后的 server 列表。

    Parameters
    ----------
    repo_root : Path or None
        仓库根，默认 ``_REPO_ROOT``。测试通过此参数注入临时目录。
    codex_home : Path or None
        Codex 全局 config 所在目录（``~/.codex``）。测试时可指向 tmp。
    """
    root = repo_root or _REPO_ROOT
    codex_dir = codex_home or (Path.home() / ".codex")

    aggregated: dict[str, McpServerInfo] = {}

    # 顺序敏感——先注册的 source 决定 command/args/env 的"权威值"
    for srv in _read_builtin_helpers():
        _merge_into(aggregated, srv)
    for srv in _read_toml_mcp_servers(
        root / ".codex" / "config.toml", source="codex_project"
    ):
        _merge_into(aggregated, srv)
    for srv in _read_toml_mcp_servers(
        codex_dir / "config.toml", source="codex_global"
    ):
        _merge_into(aggregated, srv)
    for srv in _read_mcp_json(root / ".mcp.json"):
        _merge_into(aggregated, srv)

    return sorted(aggregated.values(), key=lambda s: s.name)


def get_server(
    name: str,
    *,
    repo_root: Path | None = None,
    codex_home: Path | None = None,
) -> McpServerInfo | None:
    for srv in list_servers(repo_root=repo_root, codex_home=codex_home):
        if srv.name == name:
            return srv
    return None
