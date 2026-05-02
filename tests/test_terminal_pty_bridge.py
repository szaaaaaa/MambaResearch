"""PTY 桥模块测试（plan 2026-05-01-cli-pty-pivot Task 2）。

不依赖 ``claude`` CLI——用 Windows 自带 ``cmd /c echo`` / 短 python 子进程做
dummy spawn，覆盖 ``PtyBridge`` 的 spawn / write / resize / signal /
cleanup 行为，以及 ``build_subprocess_env`` 的 env 组合规则。

WS 路由的端到端不在本测试范围——FastAPI ``TestClient.websocket_connect``
在 PTY async generator 上跑会极慢且 flaky，路由的字节级正确性靠 spike 验证 +
集成实测覆盖。
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

import src.server.terminal.pty_bridge as bridge_mod
from src.server.claude_code.providers import (
    ProviderConfig,
    ProviderRegistryError,
)
from src.server.terminal import PtyBridge, build_subprocess_env


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


_PYTHON_EXE = sys.executable


def _python_argv(snippet: str) -> list[str]:
    """跑一段 inline python——比 cmd /c echo 跨 locale 更稳。"""
    return [_PYTHON_EXE, "-u", "-c", snippet]


@pytest.fixture
def tmp_cwd(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture(autouse=True)
def _no_active_project(monkeypatch):
    """跑测时强制 active project 为 None——build_subprocess_env 走"无 active"分支，
    避免污染开发机当前选定的项目。
    """
    from src.server.projects.registry import get_registry

    class _NullRegistry:
        def get_active(self):
            return None

    monkeypatch.setattr(
        "src.server.terminal.pty_bridge.get_registry",
        lambda: _NullRegistry(),
    )
    yield


# ---------------------------------------------------------------------------
# PtyBridge 行为
# ---------------------------------------------------------------------------


def test_bridge_spawns_and_reads_stdout(tmp_cwd: Path) -> None:
    """spawn 一段 python print，async iter 应能拿到输出。"""

    async def run() -> str:
        argv = _python_argv("print('hello-pty-bridge')")
        async with PtyBridge(argv, cwd=tmp_cwd) as pty:
            # 等子进程出完结果——用 timeout 兜底避免测试挂死
            chunks: list[str] = []
            try:
                async with asyncio.timeout(5.0):
                    async for chunk in pty.read_chunks():
                        chunks.append(chunk)
            except asyncio.TimeoutError:
                pass  # 子进程退完 EOF 后 read_chunks 自然结束；到这是兜底
            return "".join(chunks)

    out = asyncio.run(run())
    assert "hello-pty-bridge" in out


def test_bridge_write_str_round_trip(tmp_cwd: Path) -> None:
    """python 子进程读一行 stdin 再 echo 回来——验证 write_str 真的写到 stdin。"""

    snippet = (
        "import sys; line = sys.stdin.readline(); "
        "print('GOT:' + line.strip()); sys.stdout.flush()"
    )

    async def run() -> str:
        async with PtyBridge(_python_argv(snippet), cwd=tmp_cwd) as pty:
            # python 启动需要点时间——给它 0.5s 起来再写
            await asyncio.sleep(0.5)
            pty.write_str("ping\r\n")
            chunks: list[str] = []
            deadline = time.monotonic() + 5.0
            async for chunk in pty.read_chunks():
                chunks.append(chunk)
                if "GOT:ping" in "".join(chunks) or time.monotonic() > deadline:
                    break
            return "".join(chunks)

    out = asyncio.run(run())
    assert "GOT:ping" in out


def test_bridge_write_bytes_decodes_utf8(tmp_cwd: Path) -> None:
    """write_bytes 接受字节——内部 utf-8 decode 后透传 PTY。

    spike 教训：pywinpty.write 不接 bytes；write_bytes 必须先 decode。
    """
    snippet = (
        "import sys; line = sys.stdin.readline(); "
        "print('CN:' + line.strip()); sys.stdout.flush()"
    )

    async def run() -> str:
        async with PtyBridge(_python_argv(snippet), cwd=tmp_cwd) as pty:
            await asyncio.sleep(0.5)
            pty.write_bytes("你好\r\n".encode("utf-8"))
            chunks: list[str] = []
            deadline = time.monotonic() + 5.0
            async for chunk in pty.read_chunks():
                chunks.append(chunk)
                if "CN:你好" in "".join(chunks) or time.monotonic() > deadline:
                    break
            return "".join(chunks)

    out = asyncio.run(run())
    assert "CN:你好" in out


def test_bridge_resize_does_not_raise(tmp_cwd: Path) -> None:
    """resize 在 spawn 后调，不抛即算过——视觉效果靠手测。"""

    async def run() -> None:
        argv = _python_argv("import time; time.sleep(0.5); print('done')")
        async with PtyBridge(argv, cwd=tmp_cwd) as pty:
            pty.resize(120, 40)
            pty.resize(80, 24)
            # 让子进程跑完，避免 cleanup 时杀仍在跑的 python
            await asyncio.sleep(0.6)

    asyncio.run(run())


def test_bridge_signal_int_reaches_subprocess(tmp_cwd: Path) -> None:
    """signal_int 必须让阻塞 read 的子进程立刻收到 EOF 或 \\x03——证明 \\x03
    已经过 ConPTY 到达子进程层。

    Windows ConPTY 把 \\x03 转成 CTRL_C_EVENT 信号而非字节透传，所以子进程的
    ``read(1)`` 在被打断后拿到的是空 str（EOF 状态）；这反而是"信号到了"的证据
    ——没收到信号 read 就一直阻塞，5 秒 deadline 跑完什么都不会出。
    """
    snippet = (
        "import sys; data = sys.stdin.read(1); "
        "print('STDIN:' + repr(data)); sys.stdout.flush()"
    )

    async def run() -> str:
        async with PtyBridge(_python_argv(snippet), cwd=tmp_cwd) as pty:
            await asyncio.sleep(0.5)
            pty.signal_int()
            chunks: list[str] = []
            deadline = time.monotonic() + 5.0
            async for chunk in pty.read_chunks():
                chunks.append(chunk)
                if "STDIN:" in "".join(chunks) or time.monotonic() > deadline:
                    break
            return "".join(chunks)

    out = asyncio.run(run())
    # 关键：能看到 STDIN: 说明 read(1) 已被打断返回了——signal_int 真的把
    # \x03 透传到 ConPTY 并触发了 stdin 关闭/中断。具体 repr 内容（''/...）取决于
    # ConPTY 版本，不强求。
    assert "STDIN:" in out or "KeyboardInterrupt" in out


def test_terminal_pump_closes_websocket_when_pty_exits() -> None:
    """PTY EOF must close the websocket so the frontend can show the restart path."""
    from src.server.routes.terminal import _pump

    class _ExitedPty:
        async def read_chunks(self):
            if False:
                yield ""

        def write_bytes(self, data: bytes) -> None:
            raise AssertionError("write_bytes should not be called")

        def write_str(self, data: str) -> None:
            raise AssertionError("write_str should not be called")

    class _WaitingWebSocket:
        def __init__(self) -> None:
            self.closed_codes: list[int] = []

        async def send_text(self, text: str) -> None:
            raise AssertionError("send_text should not be called")

        async def receive(self) -> dict:
            await asyncio.Event().wait()
            return {"type": "websocket.disconnect"}

        async def close(self, code: int) -> None:
            self.closed_codes.append(code)

    async def run() -> list[int]:
        ws = _WaitingWebSocket()
        await asyncio.wait_for(_pump(ws, _ExitedPty()), timeout=1.0)
        return ws.closed_codes

    assert asyncio.run(run()) == [1000]


def test_terminal_no_mirror_sentinel_disables_turn_teer() -> None:
    from src.server.routes.terminal import _should_mirror

    assert _should_mirror(None) is False
    assert _should_mirror("no-mirror") is False
    assert _should_mirror("conv-real") is True


def test_bridge_aclose_terminates_subprocess(tmp_cwd: Path) -> None:
    """``aclose`` / ``__aexit__`` 必须 terminate 子进程；alive 翻 False。"""

    pty: PtyBridge

    async def run() -> bool:
        nonlocal pty
        # 跑一个会自己睡很久的子进程——必须靠 terminate 才能让它退
        argv = _python_argv("import time; time.sleep(60)")
        pty = PtyBridge(argv, cwd=tmp_cwd)
        await pty._spawn()
        assert pty.alive is True
        await pty.aclose()
        return pty.alive

    alive_after = asyncio.run(run())
    assert alive_after is False


def test_bridge_aclose_is_idempotent(tmp_cwd: Path) -> None:
    """多次 aclose 不抛——cleanup 在异常路径里可能被重复触发。"""

    async def run() -> None:
        argv = _python_argv("import time; time.sleep(60)")
        pty = PtyBridge(argv, cwd=tmp_cwd)
        await pty._spawn()
        await pty.aclose()
        await pty.aclose()
        await pty.aclose()

    asyncio.run(run())


def test_bridge_write_before_spawn_raises(tmp_cwd: Path) -> None:
    """没 spawn 就 write 是程序错——直接抛而不是静默吞。"""
    pty = PtyBridge(_python_argv("pass"), cwd=tmp_cwd)
    with pytest.raises(RuntimeError):
        pty.write_str("nope")
    with pytest.raises(RuntimeError):
        pty.write_bytes(b"nope")
    with pytest.raises(RuntimeError):
        pty.resize(80, 24)
    with pytest.raises(RuntimeError):
        pty.signal_int()


# ---------------------------------------------------------------------------
# build_subprocess_env
# ---------------------------------------------------------------------------


def test_build_env_inherits_base() -> None:
    """provider 为 None 时直接继承 base_env，PATH 等系统 env 必须保留。"""
    base = {"PATH": "C:/Windows", "FOO": "bar"}
    env = build_subprocess_env(provider=None, base_env=base)
    assert env["PATH"] == "C:/Windows"
    assert env["FOO"] == "bar"


def test_build_env_strips_stale_active_project_when_no_active(monkeypatch) -> None:
    """没 active project 时 base_env 里残留的 MAMBA_ACTIVE_PROJECT_PATH 必须清掉，
    否则 MCP 子进程会拿到陈旧路径."""
    base = {"PATH": "C:/Windows", "MAMBA_ACTIVE_PROJECT_PATH": "C:/old/project"}
    env = build_subprocess_env(provider=None, base_env=base)
    assert "MAMBA_ACTIVE_PROJECT_PATH" not in env


def test_build_env_propagates_active_project(monkeypatch, tmp_path) -> None:
    """有 active project → env 里的 MAMBA_ACTIVE_PROJECT_PATH 反映 registry 当前值。"""

    project_dir = tmp_path / "active"
    project_dir.mkdir()

    class _FakeProject:
        path = str(project_dir)

    class _FakeRegistry:
        def get_active(self):
            return _FakeProject()

    monkeypatch.setattr(
        "src.server.terminal.pty_bridge.get_registry", lambda: _FakeRegistry()
    )
    env = build_subprocess_env(provider=None, base_env={"PATH": "C:/W"})
    assert env["MAMBA_ACTIVE_PROJECT_PATH"] == str(project_dir)


def test_build_env_provider_overrides_anthropic(monkeypatch) -> None:
    """provider 非 None 时 ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL 被替换。"""
    provider = ProviderConfig(
        name="deepseek",
        base_url="http://localhost:3456",
        api_key_env="DEEPSEEK_KEY",
        default_model="deepseek-chat",
    )
    base = {
        "PATH": "C:/W",
        "DEEPSEEK_KEY": "sk-ds-secret",
        "ANTHROPIC_API_KEY": "old-anthropic",
        "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    }
    env = build_subprocess_env(provider=provider, base_env=base)
    assert env["ANTHROPIC_API_KEY"] == "sk-ds-secret"
    assert env["ANTHROPIC_BASE_URL"] == "http://localhost:3456"
    # 原 PATH 不丢
    assert env["PATH"] == "C:/W"


def test_build_env_provider_missing_key_raises() -> None:
    """provider 指向的 env key 在 base_env 里没值——按 CLAUDE.md 不兜底，直接抛。"""
    provider = ProviderConfig(
        name="deepseek",
        base_url="http://localhost:3456",
        api_key_env="DEEPSEEK_KEY",
        default_model="x",
    )
    with pytest.raises(ProviderRegistryError):
        build_subprocess_env(provider=provider, base_env={"PATH": "C:/W"})


def test_build_env_extra_overrides_all(monkeypatch) -> None:
    """``extra`` 是最高优先级——给测试场景注入用。"""
    env = build_subprocess_env(
        provider=None,
        base_env={"FOO": "1"},
        extra={"FOO": "2", "BAR": "3"},
    )
    assert env["FOO"] == "2"
    assert env["BAR"] == "3"
