"""TokenUsageTracker 单元测试。"""
from __future__ import annotations

import pytest

from src.server.bridge.auto_compact import (
    DEFAULT_CONTEXT_WINDOW,
    SessionTokenState,
    TokenUsageTracker,
    get_tracker,
    reset_tracker_for_tests,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, sec: float) -> None:
        self.now += sec


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_tracker_for_tests(None)
    yield
    reset_tracker_for_tests(None)


# ---------------------------------------------------------------------------
# observe + state accumulation
# ---------------------------------------------------------------------------


def test_observe_accumulates_delta_tokens():
    t = TokenUsageTracker(default_context_window=100_000, clock=FakeClock())
    t.observe("s1", delta_tokens=5_000)
    t.observe("s1", delta_tokens=3_000)
    assert t.get_state("s1").total_tokens == 8_000


def test_observe_absolute_tokens_overrides_running_total():
    t = TokenUsageTracker(default_context_window=100_000, clock=FakeClock())
    t.observe("s1", delta_tokens=5_000)
    t.observe("s1", absolute_tokens=42_000)
    assert t.get_state("s1").total_tokens == 42_000


def test_observe_creates_state_lazily():
    t = TokenUsageTracker(clock=FakeClock())
    assert t.get_state("never-seen") is None
    t.observe("never-seen", delta_tokens=10)
    assert t.get_state("never-seen").total_tokens == 10


def test_observe_ignores_negative_delta():
    t = TokenUsageTracker(clock=FakeClock())
    t.observe("s1", delta_tokens=10)
    t.observe("s1", delta_tokens=-5)  # 被 clamp 到 0
    assert t.get_state("s1").total_tokens == 10


def test_observe_with_empty_session_id_is_noop():
    t = TokenUsageTracker(clock=FakeClock())
    t.observe("", delta_tokens=100)
    assert t.get_state("") is None


# ---------------------------------------------------------------------------
# should_trigger threshold
# ---------------------------------------------------------------------------


def test_should_trigger_true_when_usage_above_threshold():
    t = TokenUsageTracker(threshold_ratio=0.8, default_context_window=10_000, clock=FakeClock())
    t.observe("s1", delta_tokens=8_500)
    assert t.should_trigger("s1") is True


def test_should_trigger_false_when_below_threshold():
    t = TokenUsageTracker(threshold_ratio=0.8, default_context_window=10_000, clock=FakeClock())
    t.observe("s1", delta_tokens=5_000)
    assert t.should_trigger("s1") is False


def test_should_trigger_uses_per_call_context_window_when_given():
    t = TokenUsageTracker(threshold_ratio=0.8, default_context_window=10_000, clock=FakeClock())
    t.observe("s1", delta_tokens=8_500)
    # 用更大的窗口来重算 → 不再触发
    assert t.should_trigger("s1", context_window=20_000) is False


def test_should_trigger_false_for_unknown_session():
    t = TokenUsageTracker(clock=FakeClock())
    assert t.should_trigger("ghost") is False


# ---------------------------------------------------------------------------
# cooldown after mark_triggered
# ---------------------------------------------------------------------------


def test_cooldown_blocks_repeated_trigger():
    clock = FakeClock()
    t = TokenUsageTracker(
        threshold_ratio=0.8, cooldown_sec=300, default_context_window=10_000, clock=clock
    )
    t.observe("s1", delta_tokens=9_000)
    assert t.should_trigger("s1") is True
    t.mark_triggered("s1")
    # 冷却期内即使阈值仍超也返 False
    assert t.should_trigger("s1") is False
    # 冷却期过后再次返 True
    clock.advance(301)
    assert t.should_trigger("s1") is True


def test_mark_triggered_increments_count():
    clock = FakeClock()
    t = TokenUsageTracker(threshold_ratio=0.8, cooldown_sec=10, default_context_window=10_000, clock=clock)
    t.observe("s1", delta_tokens=9_000)
    t.mark_triggered("s1")
    clock.advance(11)
    t.mark_triggered("s1")
    assert t.get_state("s1").triggered_count == 2


# ---------------------------------------------------------------------------
# enabled flag
# ---------------------------------------------------------------------------


def test_disabled_tracker_never_triggers():
    t = TokenUsageTracker(threshold_ratio=0.5, default_context_window=1000, clock=FakeClock())
    t.enabled = False
    t.observe("s1", delta_tokens=900)  # 90% — way over
    assert t.should_trigger("s1") is False


# ---------------------------------------------------------------------------
# reset_session
# ---------------------------------------------------------------------------


def test_reset_session_clears_state():
    t = TokenUsageTracker(clock=FakeClock())
    t.observe("s1", delta_tokens=100)
    t.reset_session("s1")
    assert t.get_state("s1") is None


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------


def test_get_tracker_returns_singleton():
    a = get_tracker()
    b = get_tracker()
    assert a is b


def test_reset_tracker_for_tests_replaces_singleton():
    custom = TokenUsageTracker(threshold_ratio=0.5)
    reset_tracker_for_tests(custom)
    assert get_tracker() is custom
