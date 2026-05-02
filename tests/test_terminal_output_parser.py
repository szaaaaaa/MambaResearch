"""``output_parser`` 的单元测试 —— Task 3 of plan 2026-05-01-cli-pty-pivot。

覆盖：
* :func:`strip_ansi` —— CSI / OSC / 控制字符 / \\r\\n 折叠
* :class:`TurnTeer` —— 多轮对话切分 / DB 异常吞掉 / aclose flush 兜底 /
  ANSI strip 落库前生效
"""

from __future__ import annotations

import pytest

from src.server.terminal.output_parser import TurnTeer, strip_ansi


# ---------------------------------------------------------------------------
# strip_ansi
# ---------------------------------------------------------------------------


def test_strip_ansi_csi_color() -> None:
    """CSI 着色序列必须洗掉，文本保留。"""
    raw = "\x1b[38;2;215;119;87mhello\x1b[m world"
    assert strip_ansi(raw) == "hello world"


def test_strip_ansi_osc_title() -> None:
    """OSC（终端标题等）序列以 BEL 或 ESC \\\\ 结尾，全段洗掉。"""
    raw = "\x1b]0;✳ Claude Code\x07ready"
    assert strip_ansi(raw) == "ready"


def test_strip_ansi_misc_escape() -> None:
    """ESC + single-char 类（DECPM 等）也要洗。"""
    raw = "\x1b>before\x1b=after"
    assert strip_ansi(raw) == "beforeafter"


def test_strip_ansi_control_chars_keep_newlines() -> None:
    """0x00-0x1f 控制字符洗掉但 \\n / \\t 保留。"""
    raw = "alpha\x00\x07\nbeta\tgamma"
    assert strip_ansi(raw) == "alpha\nbeta\tgamma"


def test_strip_ansi_crlf_normalized() -> None:
    """\\r\\n 折叠成 \\n；裸 \\r 也归一化。"""
    raw = "line1\r\nline2\rline3"
    assert strip_ansi(raw) == "line1\nline2\nline3"


def test_strip_ansi_collapses_blank_lines() -> None:
    """3 个以上空行收紧到 2 行，避免 prompt 重绘留下大段空白。"""
    raw = "head\n\n\n\n\ntail"
    assert strip_ansi(raw) == "head\n\ntail"


def test_strip_ansi_real_claude_banner_fragment() -> None:
    """spike 实测拿到的 claude 启动 banner 前缀——洗完应该是空的或只剩可读字符。"""
    raw = (
        "\x1b[?9001h\x1b[?1004h\x1b[?25l\x1b[2J\x1b[m\x1b[H"
        "\x1b]0;✳ Claude Code\x07"
        "\x1b[38;2;215;119;87m▐\x1b[48;2;0;0;0m▛███▜\x1b[49m▌\x1b[m"
    )
    out = strip_ansi(raw)
    # 不该有 ESC / CSI 残留
    assert "\x1b" not in out
    # 可见字符（unicode 方块 / cap）保留
    assert "▐" in out and "▛" in out


# ---------------------------------------------------------------------------
# TurnTeer
# ---------------------------------------------------------------------------


class _RecordingWriter:
    """记录每次 append_message 调用——比 mock.Mock 直观。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, **kwargs: object) -> None:
        self.calls.append(dict(kwargs))


def test_turn_teer_user_then_assistant_round_trip() -> None:
    """模拟一个完整轮次：用户输入 hello\\r → claude 输出 → next \\r flush。"""
    writer = _RecordingWriter()
    teer = TurnTeer("conv-A", writer)

    # 用户输入 + 回车 → flush turn
    teer.on_user_input(b"hello\r")
    # claude 的回复（带 ANSI 着色）
    teer.on_pty_output("\x1b[38;5;208mHi there!\x1b[m\n")
    # 下一轮 user → 触发上一轮 assistant flush
    teer.on_user_input(b"bye\r")

    teer.aclose()

    # 期望 3 条消息：
    # 1. user "hello"（第一次 \r flush）
    # 2. assistant "Hi there!"（第二次 \r 触发的 flush，先写 assistant 再写 user）
    # 3. user "bye"
    assert [(c["role"], c["text"]) for c in writer.calls] == [
        ("user", "hello"),
        ("assistant", "Hi there!"),
        ("user", "bye"),
    ]
    # served_by + conversation_id 也要对
    assert all(c["conversation_id"] == "conv-A" for c in writer.calls)
    assert writer.calls[0]["served_by"] == "user"
    assert writer.calls[1]["served_by"] == "claude"


def test_turn_teer_three_turns_meets_80pct_threshold() -> None:
    """合成 3 轮对话——应该切出 3 个 user + 3 个 assistant = 100% > 80%（acceptance #1）。"""
    writer = _RecordingWriter()
    teer = TurnTeer("conv-3T", writer)

    turns = [
        (b"hello\r", "Hi!"),
        (b"\xe4\xbd\xa0\xe5\xa5\xbd\r", "你好。"),  # "你好" utf-8
        (b"1+1?\r", "2"),
    ]
    for user_input, asst_text in turns:
        teer.on_user_input(user_input)
        teer.on_pty_output(asst_text + "\n")

    teer.aclose()

    user_calls = [c for c in writer.calls if c["role"] == "user"]
    asst_calls = [c for c in writer.calls if c["role"] == "assistant"]
    assert len(user_calls) == 3
    assert len(asst_calls) == 3
    # 顺序与原始 turn 顺序对齐
    assert [c["text"] for c in user_calls] == ["hello", "你好", "1+1?"]
    assert [c["text"] for c in asst_calls] == ["Hi!", "你好。", "2"]


def test_turn_teer_strips_ansi_before_writing() -> None:
    """落库的 text 不能含 ANSI（acceptance #2 第二段）。"""
    writer = _RecordingWriter()
    teer = TurnTeer("conv-A", writer)
    teer.on_user_input(b"go\r")
    teer.on_pty_output("\x1b[31mred answer\x1b[m\x1b]0;title\x07")
    teer.aclose()

    asst = next(c for c in writer.calls if c["role"] == "assistant")
    assert "\x1b" not in asst["text"]
    assert asst["text"] == "red answer"


def test_turn_teer_writer_exception_does_not_break(monkeypatch) -> None:
    """store_writer 抛异常被吞掉——后续 turn 仍能继续累积（acceptance #4）。"""

    call_count = {"n": 0}

    def boom_writer(**kwargs: object) -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("DB exploded")

    teer = TurnTeer("conv-x", boom_writer)
    teer.on_user_input(b"first\r")  # 触发 1 次写（user "first"），抛
    teer.on_pty_output("ack\n")
    teer.on_user_input(b"second\r")  # 触发 assistant + user 两次写——必须走通
    teer.aclose()

    # 总共 3 次尝试调用：user1（抛）+ assistant（OK）+ user2（OK）
    assert call_count["n"] == 3


def test_turn_teer_aclose_flushes_pending_assistant() -> None:
    """WS 突然断时 aclose 必须把累积的 assistant 落库——否则丢 Claude 最后一段回复。"""
    writer = _RecordingWriter()
    teer = TurnTeer("conv-Z", writer)
    teer.on_user_input(b"q\r")
    teer.on_pty_output("partial answer before disconnect")
    # 没有第二次 \r —— 模拟用户没等 claude 输完就关浏览器
    teer.aclose()

    roles = [c["role"] for c in writer.calls]
    assert roles == ["user", "assistant"]
    assert writer.calls[1]["text"] == "partial answer before disconnect"


def test_turn_teer_aclose_idempotent() -> None:
    """多次 aclose 不应重复 flush。"""
    writer = _RecordingWriter()
    teer = TurnTeer("conv-I", writer)
    teer.on_user_input(b"hi\r")
    teer.on_pty_output("hello")
    teer.aclose()
    teer.aclose()
    teer.aclose()
    # 只 flush 1 次（user hi + assistant hello）
    assert len(writer.calls) == 2


def test_turn_teer_empty_inputs_skipped() -> None:
    """on_user_input(b'') / on_pty_output('') 不该触发 store call。"""
    writer = _RecordingWriter()
    teer = TurnTeer("conv-E", writer)
    teer.on_user_input(b"")
    teer.on_pty_output("")
    teer.on_pty_output("\x1b[m   \x1b[m")  # ANSI + 全空白
    teer.aclose()
    assert writer.calls == []


def test_turn_teer_carriage_return_only_flushes_no_text() -> None:
    """用户只敲了回车没输入文本——不写空 user 行，但仍切 turn。"""
    writer = _RecordingWriter()
    teer = TurnTeer("conv-CR", writer)
    teer.on_user_input(b"\r")
    teer.on_pty_output("(empty input handled)")
    teer.on_user_input(b"real\r")
    teer.aclose()

    roles_texts = [(c["role"], c["text"]) for c in writer.calls]
    # 第一次 \r flush 时 user buf 是空（"" strip → ""）—— 不写
    # 然后 assistant "(empty input handled)" 累积
    # 第二次 \r flush：先写 assistant，再写 user "real"
    assert roles_texts == [
        ("assistant", "(empty input handled)"),
        ("user", "real"),
    ]


def test_turn_teer_ignores_writes_after_close() -> None:
    """aclose 后再调 on_user_input / on_pty_output 不该 write。"""
    writer = _RecordingWriter()
    teer = TurnTeer("conv-X", writer)
    teer.aclose()
    teer.on_user_input(b"late\r")
    teer.on_pty_output("late chunk")
    assert writer.calls == []


def test_turn_teer_user_input_with_multiple_returns_in_one_call() -> None:
    """一次 on_user_input 含多个 \\r（粘贴含换行的文本场景）—— 切多次 turn。"""
    writer = _RecordingWriter()
    teer = TurnTeer("conv-M", writer)
    # 模拟粘贴 "a\rb\rc"——3 个 user turn 之间夹的 assistant 都为空
    teer.on_user_input(b"a\rb\rc\r")
    teer.aclose()
    user_texts = [c["text"] for c in writer.calls if c["role"] == "user"]
    assert user_texts == ["a", "b", "c"]
