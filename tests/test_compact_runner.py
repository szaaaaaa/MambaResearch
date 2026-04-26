"""compact_runner 测试 — v3.2 完整版 Task 3。

只测无副作用的部分：select_messages_to_compact + build_compact_prompt。
SDK 集成（run_compact_for_claude / run_compact_for_codex）的端到端流程在
T6 浏览器手测覆盖——单元测里 mock SDK 价值不高（mock 跟生产路径行为差很远）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.server.bridge.auto_compact_config import (
    DEFAULT_CONTEXT_WINDOWS,
    AutoCompactConfig,
)
from src.server.bridge.compact_runner import (
    build_compact_prompt,
    select_messages_to_compact,
)
from src.server.projects.db import MambaDb, set_db_for_tests
from src.server.projects.messages_store import (
    Message,
    append_message,
    list_by_conversation,
)


@pytest.fixture
def temp_db(tmp_path: Path):
    db = MambaDb(db_path=tmp_path / "mamba.db")
    set_db_for_tests(db)
    db.connect()
    yield db
    set_db_for_tests(None)


def _cfg(strategy: str = "rolling", keep_recent_n: int = 3) -> AutoCompactConfig:
    return AutoCompactConfig(
        enabled=True,
        threshold_pct=80,
        strategy=strategy,  # type: ignore[arg-type]
        keep_recent_n=keep_recent_n,
        backend_context_windows=DEFAULT_CONTEXT_WINDOWS,
    )


def _make_messages(temp_db: MambaDb, n: int) -> list[Message]:
    """生成 n 条 messages，user/assistant 交替。"""
    msgs: list[Message] = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        served = "user" if role == "user" else "claude"
        m = append_message(
            conversation_id="conv-1",
            role=role,
            text=f"msg-{i}",
            served_by=served,
        )
        msgs.append(m)
    return msgs


def test_select_rolling_keeps_recent_n(temp_db: MambaDb) -> None:
    """rolling 策略：保留最后 N 条，其余进 compact。"""
    msgs = _make_messages(temp_db, 10)
    cfg = _cfg(strategy="rolling", keep_recent_n=3)
    selected = select_messages_to_compact(msgs, cfg)
    # 10 条 - 保留最后 3 = 压 7 条
    assert len(selected) == 7


def test_select_rolling_skips_when_under_threshold(temp_db: MambaDb) -> None:
    """rolling：消息数 <= keep_recent_n → 没东西压。"""
    msgs = _make_messages(temp_db, 3)
    cfg = _cfg(strategy="rolling", keep_recent_n=3)
    assert select_messages_to_compact(msgs, cfg) == []


def test_select_single_summary_compacts_everything(temp_db: MambaDb) -> None:
    """single_summary：fresh 全压。"""
    msgs = _make_messages(temp_db, 5)
    cfg = _cfg(strategy="single_summary", keep_recent_n=3)  # keep_recent_n 被忽略
    selected = select_messages_to_compact(msgs, cfg)
    assert len(selected) == 5


def test_select_skips_already_compacted(temp_db: MambaDb) -> None:
    """已 compacted=true 的不再被选中（避免循环压缩）。"""
    from src.server.projects.messages_store import mark_compacted

    msgs = _make_messages(temp_db, 5)
    # 标记前 3 条为已 compacted
    mark_compacted([m.id for m in msgs[:3]])
    fresh_msgs = list_by_conversation("conv-1")
    cfg = _cfg(strategy="rolling", keep_recent_n=1)
    selected = select_messages_to_compact(fresh_msgs, cfg)
    # 5 总, 3 已 compacted, fresh = 2, keep 1, 压 1
    assert len(selected) == 1
    # 选中的不应包括任何 compacted=true 的
    for m in selected:
        assert m.compacted is False


def test_select_skips_mambaresearch_compact_segments(temp_db: MambaDb) -> None:
    """mambaresearch_compact 段本身就是 summary，不应再被压缩。"""
    append_message(
        conversation_id="conv-1",
        role="user",
        text="一",
        served_by="user",
    )
    append_message(
        conversation_id="conv-1",
        role="system",
        text="（旧 summary）",
        served_by="mambaresearch_compact",
    )
    append_message(
        conversation_id="conv-1",
        role="assistant",
        text="二",
        served_by="claude",
    )
    msgs = list_by_conversation("conv-1")
    cfg = _cfg(strategy="single_summary", keep_recent_n=3)
    selected = select_messages_to_compact(msgs, cfg)
    # 3 条总，1 是 mambaresearch_compact 跳过 → 选中 2 条
    assert len(selected) == 2
    for m in selected:
        assert m.served_by != "mambaresearch_compact"


def test_build_compact_prompt_contains_actor_labels(temp_db: MambaDb) -> None:
    msgs = [
        append_message(conversation_id="c", role="user", text="问题", served_by="user"),
        append_message(conversation_id="c", role="assistant", text="答案", served_by="claude"),
    ]
    prompt = build_compact_prompt(msgs)
    assert "用户:" in prompt
    assert "助手(claude):" in prompt
    assert "问题" in prompt
    assert "答案" in prompt
    # 必须有 LLM 指令
    assert "总结" in prompt


def test_build_compact_prompt_includes_tool_summary(temp_db: MambaDb) -> None:
    msgs = [
        append_message(
            conversation_id="c",
            role="assistant",
            text="跑了下脚本",
            served_by="claude",
            tool_use_summary="[Claude 调用工具 Bash(ls)]",
        ),
    ]
    prompt = build_compact_prompt(msgs)
    assert "[Claude 调用工具 Bash(ls)]" in prompt
    assert "↳" in prompt  # tool 摘要的缩进 marker
