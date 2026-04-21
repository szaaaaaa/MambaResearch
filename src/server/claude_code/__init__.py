"""Claude Code SDK 会话桥接层。

封装 ``claude-agent-sdk`` 的 ``ClaudeSDKClient``，提供跨 HTTP 请求的持久多轮会话。

注意：本包不 re-export 子模块 ``session_manager`` 中的单例 ``session_manager``，
以免与子模块同名属性产生绑定冲突（``import ...session_manager`` 会拿到实例而非模块）。
消费者请直接 ``from src.server.claude_code.session_manager import session_manager``。
"""

from src.server.claude_code.serializers import serialize_block, serialize_message
from src.server.claude_code.session_manager import ClaudeSession, SessionManager

__all__ = [
    "ClaudeSession",
    "SessionManager",
    "serialize_block",
    "serialize_message",
]
