"""v3.2 完整版 Task 3 — auto-compact 执行器。

跑一次 LLM 调用把早期 messages 总结成一条 ``mambaresearch_compact`` 段，
原 messages 标 ``compacted=true``（保留原文便于回溯）。

调用入口（SSE handler 里）::

    if cfg.enabled and tracker.should_trigger(session.id, context_window=window):
        result = await run_compact_for_claude(session, conversation_id, cfg)
        if result.success:
            _emit("cc_compact_done", result.to_event_payload())

设计要点
--------
* **复用当前 backend SDK**（不自建 LLM client）—— Claude 走 ``session.client.query``
  + ``receive_response``；Codex 走 ``session.client.send_message``。这次调用
  跑在已有 ``session.lock`` 内部（caller 是 SSE _run_turn），所以 SDK 不会
  并发；compact 完成后才 ``cc_finished``。
* **不通过 _emit 持久化 compact 响应**：调用方 caller 不调用 _emit("cc_message", ...)
  for 这次 compact 调用——直接迭代 SDK 响应、内部 accumulate text。这样
  messages 表只多一条 ``mambaresearch_compact`` 行，不污染对话历史。
* **不 reset 当前 backend session**：v3.2 范围只针对"切换时 first-message
  注入"做减负；当前 backend 内的累积由各 CLI 自身 95% auto-compact 处理。
  reset session 改造留 v3.3+。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.server.bridge.auto_compact_config import AutoCompactConfig
from src.server.projects import messages_store
from src.server.projects.messages_store import Message


# ---------------------------------------------------------------------------
# 选择 + Prompt 构造（无副作用，可单元测）
# ---------------------------------------------------------------------------


def select_messages_to_compact(
    messages: list[Message],
    config: AutoCompactConfig,
) -> list[Message]:
    """挑出本次该被 compact 的消息。

    规则：
    - 跳过已经 ``compacted=true`` 的（避免循环压缩）
    - 跳过 ``served_by == 'mambaresearch_compact'`` 的（自己不应再被压缩）
    - ``rolling`` 策略：保留最后 ``keep_recent_n`` 条原文，其余进 compact
    - ``single_summary`` 策略：所有合规 messages 全部进 compact
    """
    fresh = [
        m for m in messages
        if not m.compacted and m.served_by != "mambaresearch_compact"
    ]
    if config.strategy == "single_summary":
        return fresh
    # rolling
    keep = max(config.keep_recent_n, 0)
    if len(fresh) <= keep:
        return []
    return fresh[: len(fresh) - keep]


def build_compact_prompt(messages: list[Message]) -> str:
    """把待压缩 messages 拼成 LLM-friendly prompt。

    输出形如::

        以下是历史对话片段，请总结成 200 字以内的紧凑文字，保留所有关键事实、
        决策、数字和未解决的问题。**不要**改写或评论，仅总结。

        用户: ...
        助手(claude): ...
          ↳ tool: [Claude 调用工具 Bash(ls)]
        ...

        总结：

    LLM 看到 "总结：" 后续接它的输出。
    """
    lines = [
        "以下是历史对话片段，请总结成 200 字以内的紧凑文字，保留所有关键事实、"
        "决策、数字和未解决的问题。**不要**改写或评论，仅总结。",
        "",
    ]
    for m in messages:
        if m.role == "user":
            lines.append(f"用户: {m.text}")
        elif m.role == "assistant":
            lines.append(f"助手({m.served_by}): {m.text}")
        elif m.role == "system":
            lines.append(f"系统: {m.text}")
        if m.tool_use_summary:
            for tool_line in m.tool_use_summary.splitlines():
                lines.append(f"  ↳ tool: {tool_line}")
    lines.append("")
    lines.append("总结：")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 结果数据
# ---------------------------------------------------------------------------


@dataclass
class CompactResult:
    """compact 执行结果。"""

    success: bool
    summary_id: str | None = None
    summary_excerpt: str = ""           # summary 前 100 字符（前端 marker 用）
    compacted_count: int = 0           # 被标记 compacted 的原始消息数
    error: str | None = None

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "summary_id": self.summary_id,
            "summary_excerpt": self.summary_excerpt,
            "compacted_count": self.compacted_count,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Claude 路径执行器
# ---------------------------------------------------------------------------


async def run_compact_for_claude(
    session: Any,
    conversation_id: str,
    config: AutoCompactConfig,
) -> CompactResult:
    """对 Claude session 跑一次 compact。

    复用 ``session.client``（已 connect 的 ClaudeSDKClient），调用方必须确保
    已经持有 ``session.lock``（caller = SSE _run_turn）。

    Parameters
    ----------
    session : ClaudeSession
        会话对象（含 client + id）。仅用 duck-typing：需要 ``id`` + ``client``。
    conversation_id : str
        所属 conversation。
    config : AutoCompactConfig
        策略 + keep_recent_n 等。

    Returns
    -------
    CompactResult
        success=False 时调用方应跳过 mark_triggered（让阈值仍然触发，下次再试）。
    """
    msgs = messages_store.list_by_conversation(conversation_id)
    to_compact = select_messages_to_compact(msgs, config)
    if not to_compact:
        return CompactResult(success=False, error="nothing to compact")

    prompt = build_compact_prompt(to_compact)
    try:
        await session.client.query(prompt)
        summary_text = await _consume_claude_response_text(session.client)
    except Exception as exc:
        return CompactResult(success=False, error=f"claude SDK call failed: {exc}")

    summary_text = summary_text.strip()
    if not summary_text:
        return CompactResult(success=False, error="empty summary from LLM")

    # 写 mambaresearch_compact 段 + 标记原 messages
    summary_msg = messages_store.append_message(
        conversation_id=conversation_id,
        role="system",
        text=summary_text,
        served_by="mambaresearch_compact",
    )
    n = messages_store.mark_compacted([m.id for m in to_compact])
    return CompactResult(
        success=True,
        summary_id=summary_msg.id,
        summary_excerpt=summary_text[:100],
        compacted_count=n,
    )


async def _consume_claude_response_text(client: Any) -> str:
    """迭代 SDK receive_response，把 assistant text blocks 拼接返回。"""
    parts: list[str] = []
    async for sdk_msg in client.receive_response():
        text = _extract_text_from_sdk_message(sdk_msg)
        if text:
            parts.append(text)
    return "".join(parts)


def _extract_text_from_sdk_message(sdk_msg: Any) -> str:
    """从 ``AssistantMessage`` SDK 对象取出文本块拼接。其它消息类型返空。

    这里走 duck-typing 避免 import claude_agent_sdk 类型——SDK 是 dev 依赖，
    保持本模块轻量。结构：``msg.content`` 是 list of blocks，每个 block 有
    ``text`` 属性表示 TextBlock。
    """
    content = getattr(sdk_msg, "content", None)
    if not isinstance(content, list):
        return ""
    out: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text:
            out.append(text)
    return "".join(out)


# ---------------------------------------------------------------------------
# Codex 路径执行器
# ---------------------------------------------------------------------------


async def run_compact_for_codex(
    session: Any,
    conversation_id: str,
    config: AutoCompactConfig,
) -> CompactResult:
    """对 Codex session 跑一次 compact。结构对偶 Claude 路径。"""
    msgs = messages_store.list_by_conversation(conversation_id)
    to_compact = select_messages_to_compact(msgs, config)
    if not to_compact:
        return CompactResult(success=False, error="nothing to compact")

    prompt = build_compact_prompt(to_compact)
    try:
        summary_text = await _consume_codex_response_text(session.client, prompt)
    except Exception as exc:
        return CompactResult(success=False, error=f"codex SDK call failed: {exc}")

    summary_text = summary_text.strip()
    if not summary_text:
        return CompactResult(success=False, error="empty summary from LLM")

    summary_msg = messages_store.append_message(
        conversation_id=conversation_id,
        role="system",
        text=summary_text,
        served_by="mambaresearch_compact",
    )
    n = messages_store.mark_compacted([m.id for m in to_compact])
    return CompactResult(
        success=True,
        summary_id=summary_msg.id,
        summary_excerpt=summary_text[:100],
        compacted_count=n,
    )


async def _consume_codex_response_text(client: Any, prompt: str) -> str:
    """对 Codex client 跑 send_message，累积 item/agentMessage/delta 文本。"""
    parts: list[str] = []
    async for frame in client.send_message(prompt):
        if not isinstance(frame, dict):
            continue
        if frame.get("method") != "item/agentMessage/delta":
            continue
        params = frame.get("params") or {}
        if not isinstance(params, dict):
            continue
        delta = params.get("delta")
        if isinstance(delta, str) and delta:
            parts.append(delta)
    return "".join(parts)
