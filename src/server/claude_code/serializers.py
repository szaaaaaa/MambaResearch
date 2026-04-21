"""SDK 消息与内容块的 JSON 序列化。

``claude_agent_sdk`` 的消息/块全部是 dataclass，但里面嵌套的 content 是 Python 对象而非
dict，无法直接 ``dataclasses.asdict`` 后再 JSON dump（会丢类型判别信息，也不支持嵌套的
Union 块）。本模块手写 dispatch，把它们展平成稳定的 SSE 载荷结构：

    {"type": "system" | "assistant" | "user" | "result", ...字段, "content": [块]}
    块 -> {"type": "text"|"thinking"|"tool_use"|"tool_result", ...字段}
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    MirrorErrorMessage,
    RateLimitEvent,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TaskNotificationMessage,
    TaskProgressMessage,
    TaskStartedMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)


def serialize_block(block: Any) -> dict[str, Any]:
    """将内容块转为 JSON 友好 dict。未知块按 ``type=raw`` 兜底。"""
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ThinkingBlock):
        return {
            "type": "thinking",
            "thinking": block.thinking,
            "signature": block.signature,
        }
    if isinstance(block, ToolUseBlock):
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    return {"type": "raw", "repr": repr(block)}


def _serialize_content(content: str | list[Any]) -> Any:
    """user/assistant 消息的 content 只能是字符串或块列表；非法类型让 for-in 自然抛错。"""
    if isinstance(content, str):
        return content
    return [serialize_block(b) for b in content]


def serialize_message(message: Any) -> dict[str, Any]:
    """将 SDK 消息转为前端可用的 dict。未知类型返回 ``type=unknown``。"""
    if isinstance(message, SystemMessage):
        return {"type": "system", "subtype": message.subtype, "data": message.data}

    if isinstance(message, AssistantMessage):
        return {
            "type": "assistant",
            "content": [serialize_block(b) for b in message.content],
            "model": message.model,
            "parent_tool_use_id": message.parent_tool_use_id,
            "error": message.error,
            "usage": message.usage,
            "message_id": message.message_id,
            "stop_reason": message.stop_reason,
            "session_id": message.session_id,
            "uuid": message.uuid,
        }

    if isinstance(message, UserMessage):
        return {
            "type": "user",
            "content": _serialize_content(message.content),
            "uuid": message.uuid,
            "parent_tool_use_id": message.parent_tool_use_id,
            "tool_use_result": message.tool_use_result,
        }

    if isinstance(message, ResultMessage):
        return {
            "type": "result",
            "subtype": message.subtype,
            "duration_ms": message.duration_ms,
            "duration_api_ms": message.duration_api_ms,
            "is_error": message.is_error,
            "num_turns": message.num_turns,
            "session_id": message.session_id,
            "stop_reason": message.stop_reason,
            "total_cost_usd": message.total_cost_usd,
            "usage": message.usage,
            "result": message.result,
            "structured_output": message.structured_output,
            "model_usage": message.model_usage,
            "permission_denials": message.permission_denials,
            "errors": message.errors,
            "uuid": message.uuid,
        }

    # SDK 还可能在一次 turn 里夹带这些辅助事件，全部显式序列化，避免回到 "unknown" 兜底
    if isinstance(message, RateLimitEvent):
        info = message.rate_limit_info
        return {
            "type": "rate_limit_event",
            "status": info.status,
            "resets_at": info.resets_at,
            "rate_limit_type": info.rate_limit_type,
            "utilization": info.utilization,
            "overage_status": info.overage_status,
            "overage_resets_at": info.overage_resets_at,
            "overage_disabled_reason": info.overage_disabled_reason,
            "session_id": message.session_id,
            "uuid": message.uuid,
        }

    if isinstance(message, StreamEvent):
        return {
            "type": "stream_event",
            "event": message.event,
            "parent_tool_use_id": message.parent_tool_use_id,
            "session_id": message.session_id,
            "uuid": message.uuid,
        }

    if isinstance(message, TaskStartedMessage):
        return {
            "type": "task_started",
            "task_id": message.task_id,
            "description": message.description,
            "task_type": message.task_type,
            "tool_use_id": message.tool_use_id,
            "session_id": message.session_id,
            "uuid": message.uuid,
        }

    if isinstance(message, TaskProgressMessage):
        return {
            "type": "task_progress",
            "task_id": message.task_id,
            "description": message.description,
            "last_tool_name": message.last_tool_name,
            "tool_use_id": message.tool_use_id,
            "usage": message.usage,
            "session_id": message.session_id,
            "uuid": message.uuid,
        }

    if isinstance(message, TaskNotificationMessage):
        return {
            "type": "task_notification",
            "task_id": message.task_id,
            "status": message.status,
            "output_file": message.output_file,
            "summary": message.summary,
            "tool_use_id": message.tool_use_id,
            "usage": message.usage,
            "session_id": message.session_id,
            "uuid": message.uuid,
        }

    if isinstance(message, MirrorErrorMessage):
        return {
            "type": "mirror_error",
            "subtype": message.subtype,
            "key": message.key,
            "error": message.error,
        }

    return {"type": "unknown", "repr": repr(message)}
