"""Codex session manager 后端模块（Task 5）。

包装官方 ``codex app-server`` JSON-RPC 协议的会话层，与 ``src/server/claude_code``
对偶：两个包各自提供一条独立的 Workbench session 路径（Claude 走 Claude Agent
SDK，Codex 走 codex app-server 子进程），路由层按 ``session.provider`` 分派。

本包子模块分工：

* ``session_manager`` — ``CodexSessionManager`` 生命周期 + HITL ``PermissionState``，
  与 ``claude_code.session_manager`` 同构。只依赖 ``app_server_client.AppServerClient``
  Protocol（不直接 spawn codex 进程）——便于测试时注入 fake client。
* ``app_server_client`` — ``AppServerClient`` Protocol（5ba 抽象）+ 真实的 JSON-RPC
  over stdio 客户端（5bb 落地；5ba 阶段只有 ``StubAppServerClient``）。
"""

from __future__ import annotations

from src.server.codex.app_server_client import (
    AppServerClient,
    CodexAppServerClient,
    CodexRpcError,
    CodexSchemaError,
    StubAppServerClient,
    check_schema_compatibility,
    reset_schema_cache,
)
from src.server.codex.session_manager import (
    CodexAuthError,
    CodexSession,
    CodexSessionManager,
    PermissionState,
    codex_session_manager,
)

__all__ = [
    "AppServerClient",
    "CodexAppServerClient",
    "CodexAuthError",
    "CodexRpcError",
    "CodexSchemaError",
    "CodexSession",
    "CodexSessionManager",
    "PermissionState",
    "StubAppServerClient",
    "check_schema_compatibility",
    "codex_session_manager",
    "reset_schema_cache",
]
