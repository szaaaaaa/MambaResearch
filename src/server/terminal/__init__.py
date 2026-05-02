"""PTY 桥模块——把 ``claude`` / ``codex`` CLI 二进制以 ConPTY 子进程方式跑，
通过 WebSocket 把 stdin/stdout 字节流双向桥到浏览器 xterm。

设计动机见 ``docs/plans/2026-05-01-cli-pty-pivot.md``——CLI 自带 HITL 提示 /
slash 命令 / session 生命周期，前端没必要在 SDK 之上再实现一遍。

模块外露入口：

* :class:`PtyBridge` —— 异步友好的 ``pywinpty.PtyProcess`` 包装；推荐用作
  ``async with PtyBridge(...) as pty:`` 自动 cleanup。
* :func:`build_subprocess_env` —— 组合 active project + provider env 给 CLI
  子进程用；与现有 SDK 路径的 ``build_env_for_provider`` 对偶。
"""

from src.server.terminal.pty_bridge import PtyBridge, build_subprocess_env

__all__ = ["PtyBridge", "build_subprocess_env"]
