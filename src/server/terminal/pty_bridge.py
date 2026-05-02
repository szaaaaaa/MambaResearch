"""异步 PTY 桥 —— Windows ConPTY (pywinpty) 包装。

用途
----
被 ``src/server/routes/terminal.py`` 的 WS 端点用来 spawn ``claude`` / ``codex``
CLI，作为聊天面板的字节流后端。spike 验证后做成生产模块。

关键 API
--------
:class:`PtyBridge`
    * ``async with PtyBridge(argv=..., cwd=..., env=..., dimensions=...) as pty:``
    * ``pty.write_str(s)`` / ``pty.write_bytes(b)`` —— 输入透传到 PTY stdin
    * ``pty.resize(cols, rows)`` —— 改终端 size
    * ``pty.signal_int()`` —— 等价 Ctrl+C（写 ``\\x03``）
    * ``pty.read_chunks()`` —— async generator yield ``str`` chunks，子进程退出
      或 cleanup 时自然结束

:func:`build_subprocess_env`
    把 ``os.environ`` + active project + provider env override 合一份 env dict
    给 ``PtyBridge``。

spike 教训（已编码进实现）
-----------------------
1. ``pywinpty.PtyProcess.write`` 在 v2.x 只接 ``str`` 不接 ``bytes``；
   ``write_bytes`` 内部 ``decode("utf-8", errors="replace")``。
2. ``PtyProcess.read`` 是阻塞 IO，必须 ``loop.run_in_executor`` 否则锁死事件循环。
3. WS 关闭时**必须** ``terminate(force=True)``，否则留 claude 僵尸子进程。
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

from winpty import PtyProcess

from src.server.claude_code.providers import (
    ProviderConfig,
    ProviderRegistryError,
    build_env_for_provider,
)
from src.server.projects.registry import ACTIVE_PROJECT_ENV_VAR, get_registry

logger = logging.getLogger(__name__)

DEFAULT_DIMENSIONS: tuple[int, int] = (24, 80)
DEFAULT_READ_CHUNK = 4096


class PtyBridge:
    """异步 PTY 子进程包装。

    Parameters
    ----------
    argv : Sequence[str]
        子进程命令行，例如 ``["claude"]`` 或 ``["claude", "--resume", "<sid>"]``。
    cwd : str or pathlib.Path
        子进程工作目录；调用方负责保证存在。
    env : Mapping[str, str] or None
        子进程 env；``None`` 表示继承父进程。**强烈建议**显式传——CLI 二进制
        多半依赖 ``HOME`` / ``PATH`` / ``ANTHROPIC_API_KEY`` 等。
    dimensions : tuple[int, int]
        ``(rows, cols)``——pywinpty 习惯的顺序。默认 24x80。

    上下文管理
    ---------
    实例必须通过 ``async with`` 使用——``__aenter__`` spawn，``__aexit__`` 不论
    异常都 ``terminate(force=True)``，避免子进程泄漏。
    """

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: str | Path,
        env: Mapping[str, str] | None = None,
        dimensions: tuple[int, int] = DEFAULT_DIMENSIONS,
        on_input: "Callable[[bytes], None] | None" = None,
        on_output: "Callable[[str], None] | None" = None,
    ) -> None:
        """
        Parameters
        ----------
        on_input : Callable[[bytes], None] or None
            每次 ``write_str`` / ``write_bytes`` 时被同步调用，参数是即将写入
            PTY 的字节（``write_str`` 路径会 utf-8 encode 后再调）。**钩子里
            抛任何异常都被 swallow** ——绝不影响 PTY 主写入路径。给 Task 3 的
            output tee（``TurnTeer.on_user_input``）当注入点。
        on_output : Callable[[str], None] or None
            每次 ``read_chunks`` yield 一个 chunk 前被同步调用，参数是 PTY 原始
            ``str`` 输出（含 ANSI）。同样 swallow exceptions。给 Task 3 的
            ``TurnTeer.on_pty_output`` 当注入点。
        """
        if not argv:
            raise ValueError("argv must be non-empty")
        self._argv: list[str] = list(argv)
        self._cwd: str = str(cwd)
        self._env: dict[str, str] | None = dict(env) if env is not None else None
        self._dimensions: tuple[int, int] = dimensions
        self._on_input: Callable[[bytes], None] | None = on_input
        self._on_output: Callable[[str], None] | None = on_output
        self._pty: PtyProcess | None = None
        self._closed = asyncio.Event()

    async def __aenter__(self) -> "PtyBridge":
        await self._spawn()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.aclose()

    async def _spawn(self) -> None:
        loop = asyncio.get_running_loop()

        def _do_spawn() -> PtyProcess:
            return PtyProcess.spawn(
                self._argv,
                cwd=self._cwd,
                env=self._env,
                dimensions=self._dimensions,
            )

        try:
            self._pty = await loop.run_in_executor(None, _do_spawn)
        except Exception:
            logger.exception(
                "PtyProcess.spawn failed: argv=%s cwd=%s", self._argv, self._cwd
            )
            raise

    @property
    def alive(self) -> bool:
        return self._pty is not None and self._pty.isalive()

    def write_str(self, data: str) -> None:
        if not self._pty:
            raise RuntimeError("PtyBridge not started")
        self._invoke_input_hook(data.encode("utf-8"))
        self._pty.write(data)

    def write_bytes(self, data: bytes) -> None:
        """二进制输入透传——pywinpty.write 只接 str，先 utf-8 decode。"""
        if not self._pty:
            raise RuntimeError("PtyBridge not started")
        self._invoke_input_hook(data)
        self._pty.write(data.decode("utf-8", errors="replace"))

    def _invoke_input_hook(self, data: bytes) -> None:
        if self._on_input is None:
            return
        try:
            self._on_input(data)
        except Exception:
            logger.exception("on_input hook raised; PTY write continues")

    def resize(self, cols: int, rows: int) -> None:
        if not self._pty:
            raise RuntimeError("PtyBridge not started")
        # pywinpty 顺序是 (rows, cols)
        self._pty.setwinsize(int(rows), int(cols))

    def signal_int(self) -> None:
        """等价 Ctrl+C：往 PTY stdin 写 ``\\x03``。

        注意：xterm 在用户按 Ctrl+C 时已经会通过 ``onData`` 发 ``\\x03``，
        这条路径是给"WS 客户端没经过 xterm 时也能 abort"的兜底。
        """
        if not self._pty:
            raise RuntimeError("PtyBridge not started")
        self._pty.write("\x03")

    async def read_chunks(self) -> AsyncIterator[str]:
        """异步 yield PTY 输出的 ``str`` chunk。

        ``pywinpty.read`` 是阻塞 IO，跑在默认 ThreadPoolExecutor。子进程
        退出时 ``EOFError``；cleanup 触发的 ``terminate`` 也会让 read 返回
        EOF。两种情况都干净结束 generator。
        """
        if not self._pty:
            raise RuntimeError("PtyBridge not started")
        loop = asyncio.get_running_loop()
        pty = self._pty
        while not self._closed.is_set():
            try:
                data = await loop.run_in_executor(None, pty.read, DEFAULT_READ_CHUNK)
            except EOFError:
                return
            except Exception:
                logger.exception("pty.read raised; ending read_chunks")
                return
            if not data:
                # pywinpty 在没数据时偶尔返回空 str 而不是阻塞——避免 busy-loop
                await asyncio.sleep(0.01)
                continue
            if self._on_output is not None:
                try:
                    self._on_output(data)
                except Exception:
                    logger.exception("on_output hook raised; PTY read continues")
            yield data

    async def aclose(self) -> None:
        """terminate 子进程并标记关闭。多次调用幂等。"""
        if self._closed.is_set():
            return
        self._closed.set()
        if self._pty is None:
            return
        loop = asyncio.get_running_loop()
        pty = self._pty

        def _do_terminate() -> None:
            try:
                pty.terminate(force=True)
            except Exception:
                logger.exception("pty.terminate failed")

        await loop.run_in_executor(None, _do_terminate)
        self._pty = None


# ---------------------------------------------------------------------------
# env 组合
# ---------------------------------------------------------------------------


def build_subprocess_env(
    *,
    provider: ProviderConfig | None = None,
    extra: Mapping[str, str] | None = None,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """组合 PTY 子进程的 env。

    层级（后者覆盖前者）：

    1. ``base_env``（默认 ``os.environ``）——继承父进程，含 PATH / HOME /
       系统 env。CLI 二进制定位靠这里。
    2. ``MAMBA_ACTIVE_PROJECT_PATH``——active project registry 当前值。MCP
       子进程定位 active project 靠这个 env，必须显式 propagate。
    3. ``build_env_for_provider(provider)`` —— provider 切换时把
       ``ANTHROPIC_API_KEY`` / ``ANTHROPIC_BASE_URL`` 替换；``provider`` 为
       ``None`` 表示走 Anthropic 默认（继承 base_env 的同名 key 即可）。
    4. ``extra``——调用方临时 override，主要给测试用。

    Parameters
    ----------
    provider : ProviderConfig or None
        ``None`` 走 base_env 默认；非 None 时必须 ``api_key_env`` 在 base_env
        里有值，否则抛 :class:`ProviderRegistryError`。
    extra : Mapping[str, str] or None
        最高优先级 override。
    base_env : Mapping[str, str] or None
        默认 ``os.environ``——测试场景注入受控字典。

    Returns
    -------
    dict[str, str]
        组装好的 env，可直接传 ``PtyBridge(env=...)``。
    """
    src = base_env if base_env is not None else os.environ
    env: dict[str, str] = {k: v for k, v in src.items()}

    # active project 同步：registry 在路由进程里被切换时，MAMBA_ACTIVE_PROJECT_PATH
    # 已经在 os.environ 里设好（registry._apply_active_project_env 负责）；
    # 但是测试场景或 base_env 注入时可能没有，按 registry.get_active() 兜一下。
    active = get_registry().get_active()
    if active is not None:
        env[ACTIVE_PROJECT_ENV_VAR] = active.path
    elif ACTIVE_PROJECT_ENV_VAR in env:
        # 没 active project 但 env 里残留——清掉避免子进程读到陈旧路径
        del env[ACTIVE_PROJECT_ENV_VAR]

    if provider is not None:
        env.update(build_env_for_provider(provider, os_env=src))

    if extra:
        env.update(extra)

    return env


__all__ = ["PtyBridge", "build_subprocess_env", "DEFAULT_DIMENSIONS"]
