"""PTY 输出解析与 turn tee —— Task 3 of plan 2026-05-01-cli-pty-pivot。

模块职责
--------
1. :func:`strip_ansi` —— 把 PTY 流里的 ANSI 控制序列（CSI / OSC / 单字符 ESC）+
   控制字符洗掉，留下"人能读懂"的纯文本。喂给 messages 表前用，避免存一堆
   ``\\x1b[?2026h`` 进 DB。
2. :class:`TurnTeer` —— 单 conversation 的 turn 切分 + 落库 mirror。两路输入：
   * ``on_user_input(bytes)`` —— WS 收到的 binary frame（用户键盘原始字节）
   * ``on_pty_output(str)`` —— PTY → 浏览器的 chunk
   切分启发：用户字节里看到 ``\\r`` 视为"按了回车 = 提交本轮"，flush user buf；
   下一个 ``\\r`` 之前的 PTY 输出归属本轮 assistant，flush 时间点是下一次回车
   或 ``aclose()``。

不在本模块的职责
---------------
* 真实 LLM 回复结构化（thinking / tool_use 块）—— 在 PTY 流里只看得见 ANSI
  着色文本，CLI 怎么渲染就是怎么记。turn 内部细分留给未来"如果 mamba_history
  消费方真要更细粒度时"再做。
* mamba_history MCP 查询 —— 只要 messages 表里有干净文本它就能查；具体接口由
  ``mamba_history`` MCP 模块拥有。
"""

from __future__ import annotations

import logging
import re
import time
from typing import Callable, Protocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ANSI / 控制字符剥离
# ---------------------------------------------------------------------------

# CSI: ESC [ params intermediates final-byte
_CSI_RE = re.compile(r"\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]")
# OSC: ESC ] payload (BEL | ESC \\)
_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
# 其他单字符 escape: ESC + 任一可见字符 ——CSI / OSC 已先剥过，这里只剩
# DECPAM (ESC =) / DECPNM (ESC >) / RIS (ESC c) / IND (ESC D) / 字符集切换
# (ESC ( B 等) 这种短 escape；用 ``\\x1b.`` 兜底足够。
_ESC_RE = re.compile(r"\x1b[\x20-\x7e]")
# 控制字符：保留 \t \n \r，其余 0x00-0x1f / 0x7f 全清
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 折叠裸 \r 到 \n（Windows PTY 经常给 \r\n，我们统一成 \n）
_CRLF_RE = re.compile(r"\r\n?")
# 折叠多余空白行
_BLANKS_RE = re.compile(r"\n{3,}")


def strip_ansi(text: str) -> str:
    """剥 ANSI 控制序列 + 控制字符，返回人可读纯文本。

    Parameters
    ----------
    text : str
        原始 PTY 输出（``str``，含 ANSI 序列、OSC、控制字符）。

    Returns
    -------
    str
        洗干净的文本。``\\r\\n`` 折叠成 ``\\n``；连续 3+ 行空行收紧到 2 行。
    """
    s = _CSI_RE.sub("", text)
    s = _OSC_RE.sub("", s)
    s = _ESC_RE.sub("", s)
    s = _CRLF_RE.sub("\n", s)
    s = _CTRL_RE.sub("", s)
    s = _BLANKS_RE.sub("\n\n", s)
    return s


# ---------------------------------------------------------------------------
# Turn tee → messages 表 mirror
# ---------------------------------------------------------------------------


class StoreWriter(Protocol):
    """messages_store.append_message 的最小签名——便于测试注入 mock。"""

    def __call__(
        self,
        *,
        conversation_id: str,
        role: str,
        text: str,
        served_by: str,
    ) -> object: ...


class TurnTeer:
    """单 conversation 的双向流 → messages 表 turn mirror。

    生命周期
    --------
    1. 实例化 ``TurnTeer(conversation_id, store_writer)``——``store_writer``
       通常就是 ``messages_store.append_message``（按位置传 kwargs）。
    2. WS 路由把 ``on_user_input`` 挂到 ``PtyBridge.on_input``，把
       ``on_pty_output`` 挂到 ``on_output``。
    3. WS 关闭时调 ``aclose()``——flush 残留的 assistant buffer。

    切分启发（DP3 兜底友好）
    ----------------------
    * 用户每次按回车（user input 字节里出现 ``\\r``）= 一轮 user 消息提交。
      此时 flush 之前累积的 assistant buf（属于上一轮 Claude 的回复），再 flush
      user buf（本轮用户输入）。
    * 假定每轮严格交替 user → assistant → user → ...。多轮 user 输入连发（偶发
      copy-paste 含多个 \\r）会切成多条 user 行，assistant 行可能为空。
    * ``aclose()`` 把当前 buf 兜底 flush——避免 WS 突然断时丢最后一段 assistant。
    * ``store_writer`` 抛任何异常都吞到 logger，**绝不**让 PTY 主流断（acceptance #4）。
    """

    def __init__(self, conversation_id: str, store_writer: StoreWriter) -> None:
        self._conv_id = conversation_id
        self._writer = store_writer
        self._user_buf: list[str] = []
        self._asst_buf: list[str] = []
        self._closed = False

    def on_user_input(self, data: bytes) -> None:
        """从 WS binary frame 收到的用户键盘字节——可能含输入字符 + \\r。"""
        if self._closed or not data:
            return
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            logger.exception("on_user_input decode failed")
            return
        # 以 \r 切分：每个 \r 触发一次 flush，剩余字符继续累积
        parts = text.split("\r")
        # parts[0] 拼到当前 user buf；parts[1..n-1] 各 flush 一次；parts[n-1] 留作下轮
        self._user_buf.append(parts[0])
        for piece in parts[1:-1]:
            self._flush_turn()
            self._user_buf.append(piece)
        if len(parts) >= 2:
            # 最后一个 \r 触发 flush；parts[-1] 是新 buf 起点
            self._flush_turn()
            self._user_buf.append(parts[-1])

    def on_pty_output(self, chunk: str) -> None:
        """PTY → 浏览器的 str chunk——一律累积到 assistant buf。"""
        if self._closed or not chunk:
            return
        self._asst_buf.append(chunk)

    def aclose(self) -> None:
        """会话结束 flush 兜底。多次调用幂等。"""
        if self._closed:
            return
        try:
            self._flush_turn()
        finally:
            self._closed = True

    def _flush_turn(self) -> None:
        """flush 当前 assistant buf（属于上一轮 Claude）+ user buf（本轮用户输入）。

        顺序：先写 assistant（属于上一轮），再写 user（本轮）；这样 messages 表
        按 created_at 升序读出来 = 真实对话顺序。
        """
        # 先 flush 之前的 assistant
        if self._asst_buf:
            raw = "".join(self._asst_buf)
            self._asst_buf.clear()
            clean = strip_ansi(raw).strip()
            if clean:
                self._safe_write(role="assistant", text=clean, served_by="claude")
        # 再 flush 用户输入
        if self._user_buf:
            user_raw = "".join(self._user_buf)
            self._user_buf.clear()
            user_clean = strip_ansi(user_raw).strip()
            if user_clean:
                self._safe_write(role="user", text=user_clean, served_by="user")

    def _safe_write(self, *, role: str, text: str, served_by: str) -> None:
        """调 store_writer，吞掉任何异常——不让 DB 故障影响 PTY 主流。"""
        try:
            self._writer(
                conversation_id=self._conv_id,
                role=role,
                text=text,
                served_by=served_by,
            )
        except Exception:
            logger.exception(
                "TurnTeer write failed (role=%s, conv=%s, len=%d)",
                role,
                self._conv_id,
                len(text),
            )


__all__ = ["strip_ansi", "TurnTeer", "StoreWriter"]
