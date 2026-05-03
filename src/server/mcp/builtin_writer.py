"""把 builtin MCP server 配置写到 active project 内供 PTY claude 加载。

PTY 模式（cli-pty-pivot Task 2 后）下 ResearchAgent 直接 spawn ``claude`` CLI，
不再走 SDK options 注入 MCP servers。Claude CLI 通过 ``--mcp-config <path>``
加载额外 MCP server 配置；本模块负责把 6 个 MambaResearch builtin server 的
``default_mcp_config`` 序列化到 ``<project>/.mambaresearch/mcp_config.json``。

active project 切换 / 启动时由 ``src/server/projects/registry.py`` 的
``_apply_active_project_env`` 调用，PTY ``pty_bridge.py`` spawn 时把该路径
通过 ``--mcp-config`` 传给 claude 二进制。

为何不直接写 ``.mcp.json``：``.mcp.json`` 是 user-managed 配置文件（用户在
项目级显式注册的 server）；builtin server 是 ResearchAgent 自动维护的，不
应该混进 user 文件。``.mambaresearch/mcp_config.json`` 是 ResearchAgent 私有
托管目录（已在 ``.gitignore``）下的覆写文件，每次 activate 时整盘重写。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BUILTIN_CONFIG_FILE = "mcp_config.json"
_PROJECT_META_DIR = ".mambaresearch"

logger = logging.getLogger(__name__)


def _collect_builtin_servers() -> dict[str, dict]:
    """收集 6 个 builtin MCP server 的 default_mcp_config 输出。

    延迟 import 避免本模块被启动期 IO / 测试 fixture 拖慢；同时保留每个
    server 自己的 ``MAMBA_*_MCP_DISABLED`` env 关闭逻辑（关闭的 server 返回
    空 dict，不会进入合并结果）。
    """
    from src.server.integrations.colab.mcp_server import (
        default_mcp_config as colab_cfg,
    )
    from src.server.integrations.experiment.mcp_server import (
        default_mcp_config as experiment_cfg,
    )
    from src.server.integrations.mamba_history.mcp_server import (
        default_mcp_config as mamba_history_cfg,
    )
    from src.server.integrations.paper_search.mcp_server import (
        default_mcp_config as paper_search_cfg,
    )
    from src.server.integrations.zotero.mcp_server import (
        default_mcp_config as zotero_cfg,
    )
    from src.server.workspace.mcp_server import (
        default_mcp_config as workspace_cfg,
    )

    servers: dict[str, dict] = {}
    for fn in (
        workspace_cfg,
        zotero_cfg,
        colab_cfg,
        experiment_cfg,
        mamba_history_cfg,
        paper_search_cfg,
    ):
        servers.update(fn(_REPO_ROOT))
    return servers


def builtin_mcp_config_path(project_path: str | Path) -> Path:
    """返回 ``<project>/.mambaresearch/mcp_config.json`` 绝对路径。

    pty_bridge spawn 时把该路径通过 ``--mcp-config`` 传给 claude；调用方负
    责检查文件是否存在再传 flag。
    """
    return Path(project_path) / _PROJECT_META_DIR / _BUILTIN_CONFIG_FILE


def write_builtin_mcp_config(project_path: str | Path) -> Path | None:
    """整盘重写 active project 的 builtin mcp_config.json。

    Parameters
    ----------
    project_path : str | Path
        active project 的根目录路径。需可写——在网络盘 / 只读卷上写失败时
        记 warning 不抛，返回 ``None`` 让 PTY spawn 回退到无 ``--mcp-config``
        模式（claude 仍可用，只是看不到 builtin MCP）。

    Returns
    -------
    Path | None
        成功写入时返回文件路径；写失败（OSError / 路径不可访问）返回 ``None``。
    """
    target = builtin_mcp_config_path(project_path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        servers = _collect_builtin_servers()
        payload = json.dumps(
            {"mcpServers": servers},
            ensure_ascii=False,
            indent=2,
        )
        target.write_text(payload, encoding="utf-8", newline="\n")
        return target
    except OSError as exc:
        logger.warning(
            "write_builtin_mcp_config failed at %s: %s; PTY claude 将看不到 builtin MCP",
            target,
            exc,
        )
        return None
