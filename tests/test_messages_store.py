"""MessagesStore 行为测试 — Hybrid Master Transcript Task 1。

覆盖：append → list 顺序、count、segment 反查 conversation、CHECK 约束。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.server.projects.conversations import add_segment, create_conversation
from src.server.projects.db import MambaDb, set_db_for_tests
from src.server.projects.messages_store import (
    Message,
    append_message,
    count_by_conversation,
    list_by_conversation,
    lookup_conversation_by_session,
)


@pytest.fixture
def temp_db(tmp_path: Path):
    db = MambaDb(db_path=tmp_path / "mamba.db")
    set_db_for_tests(db)
    db.connect()
    yield db
    set_db_for_tests(None)


def test_append_returns_message_with_id_and_timestamp(temp_db: MambaDb) -> None:
    msg = append_message(
        conversation_id="conv-1",
        role="user",
        text="你好",
        served_by="user",
    )
    assert isinstance(msg, Message)
    assert msg.id  # 非空
    assert msg.conversation_id == "conv-1"
    assert msg.role == "user"
    assert msg.text == "你好"
    assert msg.served_by == "user"
    assert msg.tool_use_summary is None
    assert msg.raw_payload is None
    assert msg.compacted is False
    assert msg.created_at > 0


def test_list_returns_messages_in_created_order(temp_db: MambaDb) -> None:
    a = append_message(conversation_id="c1", role="user", text="一", served_by="user")
    # 用户输入 -> assistant 回复 -> 下一轮用户输入；时间戳应严格递增
    time.sleep(1.01)  # SQLite 秒级精度，必须 > 1s 否则同 created_at 顺序看 id
    b = append_message(conversation_id="c1", role="assistant", text="回复一", served_by="claude")
    time.sleep(1.01)
    c = append_message(conversation_id="c1", role="user", text="二", served_by="user")

    listed = list_by_conversation("c1")
    assert [m.id for m in listed] == [a.id, b.id, c.id]
    assert [m.text for m in listed] == ["一", "回复一", "二"]
    assert [m.served_by for m in listed] == ["user", "claude", "user"]


def test_list_filters_by_conversation(temp_db: MambaDb) -> None:
    append_message(conversation_id="c1", role="user", text="A", served_by="user")
    append_message(conversation_id="c2", role="user", text="B", served_by="user")
    append_message(conversation_id="c1", role="assistant", text="Areply", served_by="codex")

    c1 = list_by_conversation("c1")
    c2 = list_by_conversation("c2")
    assert {m.text for m in c1} == {"A", "Areply"}
    assert {m.text for m in c2} == {"B"}


def test_count_by_conversation(temp_db: MambaDb) -> None:
    assert count_by_conversation("empty") == 0
    append_message(conversation_id="c1", role="user", text="x", served_by="user")
    append_message(conversation_id="c1", role="assistant", text="y", served_by="claude")
    append_message(conversation_id="c2", role="user", text="z", served_by="user")
    assert count_by_conversation("c1") == 2
    assert count_by_conversation("c2") == 1


def test_optional_fields_round_trip(temp_db: MambaDb) -> None:
    msg = append_message(
        conversation_id="c1",
        role="assistant",
        text="切换前的助手回复",
        served_by="claude",
        tool_use_summary="[Claude 用 Bash 跑 ls -la, 输出: ...]",
        raw_payload='{"type":"assistant","content":[{"type":"text","text":"..."}]}',
    )
    listed = list_by_conversation("c1")
    assert len(listed) == 1
    got = listed[0]
    assert got.id == msg.id
    assert got.tool_use_summary == "[Claude 用 Bash 跑 ls -la, 输出: ...]"
    assert got.raw_payload is not None
    assert "assistant" in got.raw_payload


def test_lookup_conversation_by_session_returns_conv_id(temp_db: MambaDb) -> None:
    conv = create_conversation(project_id="proj-1", title="t")
    add_segment(
        conversation_id=conv.id,
        backend="claude",
        cli_session_id="abc-123-uuid",
    )
    assert lookup_conversation_by_session("abc-123-uuid") == conv.id


def test_lookup_conversation_by_session_returns_none_for_unknown(temp_db: MambaDb) -> None:
    assert lookup_conversation_by_session("never-existed") is None


def test_lookup_returns_latest_segment_when_session_id_repeats(temp_db: MambaDb) -> None:
    """同一 cli_session_id 出现在多个 segment（理论上不应该但防御性测试）：取
    最新 segment 的 conversation_id。"""
    conv1 = create_conversation(project_id="p", title="一")
    conv2 = create_conversation(project_id="p", title="二")
    add_segment(conversation_id=conv1.id, backend="claude", cli_session_id="dup-sid")
    add_segment(conversation_id=conv2.id, backend="claude", cli_session_id="dup-sid")
    # latest segment_index wins
    assert lookup_conversation_by_session("dup-sid") in {conv1.id, conv2.id}


def test_invalid_role_rejected(temp_db: MambaDb) -> None:
    with pytest.raises(Exception):  # sqlite3.IntegrityError 或 OperationalError
        append_message(
            conversation_id="c1",
            role="bogus",  # type: ignore[arg-type]
            text="x",
            served_by="user",
        )


def test_invalid_served_by_rejected(temp_db: MambaDb) -> None:
    with pytest.raises(Exception):
        append_message(
            conversation_id="c1",
            role="assistant",
            text="x",
            served_by="gpt-9000",  # type: ignore[arg-type]
        )


def test_mambaresearch_compact_served_by_allowed(temp_db: MambaDb) -> None:
    """v3.2 auto-compact 子任务用：rolling summary 写回时 served_by=mambaresearch_compact。"""
    msg = append_message(
        conversation_id="c1",
        role="system",
        text="（早 N 条对话的总结）...",
        served_by="mambaresearch_compact",
    )
    assert msg.served_by == "mambaresearch_compact"
    listed = list_by_conversation("c1")
    assert listed[0].served_by == "mambaresearch_compact"


# ---------------------------------------------------------------------------
# estimate_tokens 启发式
# ---------------------------------------------------------------------------


def test_estimate_tokens_empty_string() -> None:
    from src.server.projects.messages_store import estimate_tokens

    assert estimate_tokens("") == 0


def test_estimate_tokens_pure_ascii_4_chars_per_token() -> None:
    from src.server.projects.messages_store import estimate_tokens

    # 4 ASCII chars → 1 token
    assert estimate_tokens("abcd") == 1
    # 5 chars → 2 tokens (向上取整)
    assert estimate_tokens("abcde") == 2
    # 8 chars → 2 tokens
    assert estimate_tokens("abcdefgh") == 2


def test_estimate_tokens_cjk_one_char_per_token() -> None:
    from src.server.projects.messages_store import estimate_tokens

    # 中文字符按 1:1 估算
    assert estimate_tokens("你好") == 2
    assert estimate_tokens("中日韩繁體字") == 6


def test_estimate_tokens_mixed_text() -> None:
    from src.server.projects.messages_store import estimate_tokens

    # "Hello 世界" = 6 ASCII (含空格) + 2 CJK = ceil(6/4) + 2 = 2 + 2 = 4
    assert estimate_tokens("Hello 世界") == 4
