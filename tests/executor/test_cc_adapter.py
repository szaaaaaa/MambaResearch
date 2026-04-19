"""Claude Code 适配器测试。

三个测试覆盖验收标准：

1. test_adapter_streams_lines_and_emits_events —— 用 fake "CLI"（python 进程打印 3
   行）验证 stdout 每行生成一个 CCStreamEvent、CCResult.stdout 完整。
2. test_adapter_timeout_kills_process —— fake CLI 睡 30 秒，timeout_sec=0.5 应抛
   CCTimeoutError，总线收到 channel="timeout" 事件，实际耗时 < 5s。
3. test_adapter_real_claude_hello —— 集成测试：真调 claude，要求在工作区生成
   hello.py。如 PATH 无 claude 则 skip，CI 环境友好。

依赖：不使用 pytest-asyncio，沿用项目约定的 asyncio.run() 包装。
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import textwrap
from pathlib import Path

import pytest

from src.dynamic_os.executor.cc_adapter import (
    CCResult,
    CCStreamEvent,
    CCTimeoutError,
    ClaudeCodeExecutor,
)


def _make_fake_claude_script(tmp_path: Path, body: str) -> Path:
    """把一段 python 代码写成脚本，返回路径。测试用这个当作 fake claude。"""
    script = tmp_path / "fake_claude.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return script


class _FakeClaudeExecutor(ClaudeCodeExecutor):
    """测试用子类，用 `python <fake_script>` 代替真实 `claude -p <prompt>`。

    通过覆盖 _build_cli_args 让子进程命令变成 `[python, fake_script]`，
    完全绕过 claude CLI 以便在任何环境下跑。fake_script 自行决定输出和退出时机。
    """

    def __init__(self, *, fake_script: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._fake_script = fake_script

    def _build_cli_args(self, *, prompt: str, extra_args: list[str] | None) -> list[str]:
        args = [sys.executable, str(self._fake_script)]
        if extra_args:
            args.extend(extra_args)
        return args


def test_adapter_streams_lines_and_emits_events(tmp_path: Path) -> None:
    """验证 AC：子进程 stdout 每一行都产生一个 CCStreamEvent 进入 bus。"""
    script = _make_fake_claude_script(
        tmp_path,
        """
        import sys
        print("line-one", flush=True)
        print("line-two", flush=True)
        print("line-three", flush=True)
        sys.exit(0)
        """,
    )
    captured: list[object] = []

    async def _run() -> CCResult:
        workspace = tmp_path / "ws"
        executor = _FakeClaudeExecutor(
            fake_script=script,
            event_sink=captured.append,
            default_timeout_sec=10.0,
        )
        return await executor.run(
            prompt="dummy",
            workspace=workspace,
            run_id="run-stream-1",
        )

    result = asyncio.run(_run())

    stream_events = [e for e in captured if isinstance(e, CCStreamEvent)]
    stdout_events = [e for e in stream_events if e.channel == "stdout"]
    assert len(stdout_events) >= 3, f"expected ≥3 stdout events, got {len(stdout_events)}"
    stdout_lines = [e.line for e in stdout_events]
    assert "line-one" in stdout_lines
    assert "line-two" in stdout_lines
    assert "line-three" in stdout_lines
    assert all(e.run_id == "run-stream-1" for e in stdout_events)
    assert result.exit_code == 0
    assert "line-one" in result.stdout and "line-three" in result.stdout


def test_adapter_timeout_kills_process(tmp_path: Path) -> None:
    """验证 AC：超时后 kill 进程 + 发 timeout 事件 + 抛 CCTimeoutError。"""
    script = _make_fake_claude_script(
        tmp_path,
        """
        import time
        # 睡足够久以保证触发超时
        time.sleep(30)
        """,
    )
    captured: list[object] = []

    async def _run() -> None:
        executor = _FakeClaudeExecutor(
            fake_script=script,
            event_sink=captured.append,
        )
        await executor.run(
            prompt="dummy",
            workspace=tmp_path / "ws",
            run_id="run-timeout-1",
            timeout_sec=0.5,
        )

    import time as _time

    started = _time.perf_counter()
    with pytest.raises(CCTimeoutError) as exc_info:
        asyncio.run(_run())
    elapsed = _time.perf_counter() - started

    assert elapsed < 5.0, f"timeout handling took {elapsed}s — process not killed promptly"
    assert exc_info.value.duration_sec > 0
    timeout_events = [
        e for e in captured
        if isinstance(e, CCStreamEvent) and e.channel == "timeout"
    ]
    assert len(timeout_events) == 1
    assert timeout_events[0].run_id == "run-timeout-1"


@pytest.mark.skipif(
    shutil.which("claude") is None,
    reason="claude CLI not on PATH — skip integration test",
)
def test_adapter_real_claude_hello(tmp_path: Path) -> None:
    """集成 AC：真实调 claude，workspace 应包含新建的 hello.py。

    本测试调用真实 Claude Code 订阅，耗时 10-60s。PATH 无 claude 时 skip。
    """
    captured: list[object] = []
    workspace = tmp_path / "ws"

    async def _run() -> CCResult:
        executor = ClaudeCodeExecutor(
            event_sink=captured.append,
            default_timeout_sec=120.0,
        )
        return await executor.run(
            prompt=(
                "In the current directory, create a file named hello.py "
                "whose content is exactly: print('hi')\n"
                "Do not create any other files."
            ),
            workspace=workspace,
            run_id="run-integration-1",
            permission_mode="bypassPermissions",
        )

    result = asyncio.run(_run())

    assert result.exit_code == 0, (
        f"claude exited with {result.exit_code}; "
        f"stderr={result.stderr[:500]}"
    )
    hello_py = workspace / "hello.py"
    assert hello_py.exists(), (
        f"hello.py not created in workspace; "
        f"workspace contents: {[p.name for p in workspace.iterdir()]}"
    )
    content = hello_py.read_text(encoding="utf-8")
    assert "hi" in content
    stream_events = [e for e in captured if isinstance(e, CCStreamEvent)]
    assert len(stream_events) >= 1
