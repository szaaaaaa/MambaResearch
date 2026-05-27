"""Claude Code 历史会话存储层。

经 CLI PTY pivot 后，本包只剩两块：

* :mod:`storage` —— DB 持久化（sessions + messages），路由层只读使用
* :mod:`providers` —— provider registry，被 ``terminal/pty_bridge`` 与
  ``routes/cli_providers`` 复用，与 SDK 无关

实时聊天走 PTY（``terminal/pty_bridge.py``），不再有 SDK client / serializers /
session_manager。``claude-agent-sdk`` 不再是项目运行时依赖。
"""
