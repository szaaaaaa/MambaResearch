"""Auto-compact 兜底——监听 token usage，必要时建议 segment break。

设计要点
~~~~~~~~
* **不依赖 Codex 是否原生有 auto-compact**：MambaResearch 兜底监听 SSE 中
  的 token usage 累积，超阈值时**建议**前端弹"自动 compact"提示。是否
  真的执行 conversation_switch 由前端 / 用户决定（保守路径——避免在长
  脚本运行中被静默 reset 上下文）。
* **per-session 累积**：进程级 ``TokenUsageTracker`` 单例 keyed by
  cli_session_id，避免跨 session 误干扰。
* **冷却期**：触发后默认 5 分钟内不再次推荐——避免连续告警洪水。

集成点（待 SSE 嵌入）
~~~~~~~~~~~~~~~~~~~~
``src/server/routes/codex.py`` 的 ``_emit`` 已经有 ``mcp_logger.observe_codex_event``
的 pattern，按同样方式调 ``token_tracker.observe_event(...)``，返回值若
``True`` 即在 SSE 流中再 emit 一帧 ``auto_compact_recommended``，前端展示
banner + 让用户点 "压缩"。

本 stage（Task 10）只交付**模块本身 + 单元测试**。Codex SSE wiring 与端到端
auto-trigger 留 PENDING-VERIFY，避免在 long-running session 中引入潜在 race。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 配置常量
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLD_RATIO = 0.80
"""默认触发阈值——已用 token / 上下文窗口 ≥ 0.80。"""

DEFAULT_COOLDOWN_SEC = 5 * 60
"""触发一次后的冷却秒数。"""

DEFAULT_CONTEXT_WINDOW = 200_000
"""当事件中没有给上下文窗口大小时使用的保守默认。"""


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class SessionTokenState:
    """单个 cli_session_id 的累计状态。"""

    session_id: str
    total_tokens: int = 0
    last_event_at: float = field(default_factory=time.time)
    last_triggered_at: float = 0.0
    triggered_count: int = 0

    def usage_ratio(self, context_window: int) -> float:
        if context_window <= 0:
            return 0.0
        return self.total_tokens / context_window


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------


class TokenUsageTracker:
    """进程级 per-session token 累计 + 触发判断。

    Parameters
    ----------
    threshold_ratio
        ``total_tokens / context_window`` 达此值时建议 compact。
    cooldown_sec
        触发一次后的冷却期；冷却期内 ``should_trigger`` 即使阈值仍超也返 False。
    default_context_window
        事件未给 context_window 时使用的保守默认。
    """

    def __init__(
        self,
        *,
        threshold_ratio: float = DEFAULT_THRESHOLD_RATIO,
        cooldown_sec: float = DEFAULT_COOLDOWN_SEC,
        default_context_window: int = DEFAULT_CONTEXT_WINDOW,
        clock=None,
    ) -> None:
        self.threshold_ratio = threshold_ratio
        self.cooldown_sec = cooldown_sec
        self.default_context_window = default_context_window
        self._clock = clock or time.time
        self._states: dict[str, SessionTokenState] = {}
        self._lock = threading.Lock()
        self.enabled = True

    # -------- 公开 API -------------------------------------------------

    def get_state(self, session_id: str) -> SessionTokenState | None:
        with self._lock:
            return self._states.get(session_id)

    def reset_session(self, session_id: str) -> None:
        """触发 compact 后调；新 session 的累计从 0 开始。"""
        with self._lock:
            self._states.pop(session_id, None)

    def observe(
        self,
        session_id: str,
        *,
        delta_tokens: int = 0,
        absolute_tokens: int | None = None,
    ) -> None:
        """记一次 token usage 事件。

        Parameters
        ----------
        session_id
            cli_session_id，必填。
        delta_tokens
            本次新增 token；``absolute_tokens`` 给定时本参数被忽略。
        absolute_tokens
            如果事件给的是累计值（如 Codex turn-end usage 字段），用这个直接覆盖。
        """
        if not session_id:
            return
        now = self._clock()
        with self._lock:
            state = self._states.get(session_id)
            if state is None:
                state = SessionTokenState(session_id=session_id)
                self._states[session_id] = state
            if absolute_tokens is not None and absolute_tokens >= 0:
                state.total_tokens = absolute_tokens
            else:
                state.total_tokens += max(delta_tokens, 0)
            state.last_event_at = now

    def should_trigger(
        self,
        session_id: str,
        *,
        context_window: int | None = None,
    ) -> bool:
        """判断当前是否应建议 compact。

        Returns
        -------
        bool
            True → 推荐 compact；调用方负责 ``mark_triggered`` 标记。
            disabled / 冷却期内 / 未达阈值 / session 未注册 → False。
        """
        if not self.enabled:
            return False
        with self._lock:
            state = self._states.get(session_id)
            if state is None:
                return False
            now = self._clock()
            if (now - state.last_triggered_at) < self.cooldown_sec and state.triggered_count > 0:
                return False
            window = context_window if context_window and context_window > 0 else self.default_context_window
            return state.usage_ratio(window) >= self.threshold_ratio

    def mark_triggered(self, session_id: str) -> None:
        """记录一次推荐触发——开始冷却 + 计数 +1。"""
        with self._lock:
            state = self._states.get(session_id)
            if state is None:
                return
            state.last_triggered_at = self._clock()
            state.triggered_count += 1


# ---------------------------------------------------------------------------
# 进程级单例
# ---------------------------------------------------------------------------


_TRACKER: TokenUsageTracker | None = None
_TRACKER_LOCK = threading.Lock()


def get_tracker() -> TokenUsageTracker:
    global _TRACKER
    with _TRACKER_LOCK:
        if _TRACKER is None:
            _TRACKER = TokenUsageTracker()
        return _TRACKER


def reset_tracker_for_tests(tracker: TokenUsageTracker | None = None) -> None:
    global _TRACKER
    with _TRACKER_LOCK:
        _TRACKER = tracker
