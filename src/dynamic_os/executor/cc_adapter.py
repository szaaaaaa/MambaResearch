"""Claude Code 子进程适配器 —— 将 `claude -p` 封装为可观测的异步调用。

提供 ML 实验执行引擎所需的基础能力：

1. 启动 Claude Code CLI 子进程，在指定工作目录内执行
2. 流式捕获 stdout/stderr，每行产生一个 CCStreamEvent 推送到 event bus
3. 支持 timeout_sec，超时后强制 kill 进程并抛出 CCTimeoutError
4. 关闭 stdin 防止子进程等待输入永久挂起（Windows 常见坑）

本模块不触碰 contracts 目录（🔴 禁区），事件类型 CCStreamEvent 为适配器本地
定义的轻量 dataclass，通过现有 EventSink 回调推送。调用者（如 run_experiment
技能）负责把这些细粒度流事件与顶层 Observation 对齐。

⚠️ permission_mode 坑点
-----------------------
ML 实验场景必须显式传 `permission_mode="bypassPermissions"`（或 "acceptEdits"）。
默认 None 会让 `claude -p` 静默拒绝工具调用——子进程仍返回 exit_code=0 但工作区
空空如也，agent 只是在 stdout 里"叙述"自己要做什么。调试时极易误判。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


# 事件推送回调类型，与 executor/node_runner 中的 EventSink 语义一致
EventSink = Callable[[object], None]


@dataclass(frozen=True)
class CCStreamEvent:
    """Claude Code 子进程输出的单行流式事件。

    子进程每产生一行 stdout/stderr，就生成一个 CCStreamEvent 推入 event bus。
    额外用 channel="timeout" 在超时杀进程时发一个终止标记事件，便于前端展示。
    """

    # ISO 格式时间戳（UTC）
    ts: str
    # 所属运行 ID，由调用者传入；未指定则为空串
    run_id: str
    # 事件通道："stdout" / "stderr" / "timeout"
    channel: str
    # 捕获的文本行（已去除末尾换行），timeout 事件则为终止原因描述
    line: str


@dataclass(frozen=True)
class CCResult:
    """`claude -p` 调用的最终结果汇总。"""

    # 子进程退出码（0 表示成功）
    exit_code: int
    # 合并后的 stdout 全文（按行用 \n 连接）
    stdout: str
    # 合并后的 stderr 全文
    stderr: str
    # 总耗时（秒）
    duration_sec: float
    # 子进程实际使用的工作目录
    workspace: Path


class CCTimeoutError(TimeoutError):
    """Claude Code 子进程超过 timeout_sec 被 kill 后抛出。

    附带已捕获的部分输出，便于调用者诊断超时前的进度。
    继承自 TimeoutError，可被 node_runner 的超时分支直接捕获。
    """

    def __init__(
        self,
        message: str,
        *,
        partial_stdout: str = "",
        partial_stderr: str = "",
        duration_sec: float = 0.0,
    ) -> None:
        super().__init__(message)
        # 超时前已收到的 stdout 片段
        self.partial_stdout = partial_stdout
        # 超时前已收到的 stderr 片段
        self.partial_stderr = partial_stderr
        # 实际执行时长（秒）
        self.duration_sec = duration_sec


class ClaudeCodeExecutor:
    """Claude Code 子进程适配器，异步调用 `claude -p <prompt>`。

    设计要点
    --------
    - 非交互模式（`-p`）：一次性 prompt 调用，适合作为实验执行引擎
    - stdin 关闭（DEVNULL）：避免 CLI 在无终端环境下等待输入挂起
    - 流式 IO：stdout/stderr 按行捕获，每行推事件，前端可实时展示
    - 强制 UTF-8 解码 + errors="replace"：规避 Windows 控制台 GBK 编码坑
    - 超时强 kill：用 asyncio.wait_for 等进程退出，超时则 process.kill()
    """

    def __init__(
        self,
        *,
        claude_bin: str | None = None,
        event_sink: EventSink | None = None,
        default_timeout_sec: float = 600.0,
    ) -> None:
        # Claude Code 二进制路径或命令名，优先顺序：显式参数 > 环境变量 > "claude"
        self._claude_bin = (
            claude_bin
            or os.environ.get("CLAUDE_CODE_BIN")
            or "claude"
        )
        self._event_sink = event_sink
        self._default_timeout_sec = default_timeout_sec

    async def run(
        self,
        *,
        prompt: str,
        workspace: Path,
        run_id: str = "",
        timeout_sec: float | None = None,
        permission_mode: str | None = None,
        extra_args: list[str] | None = None,
    ) -> CCResult:
        """启动 `claude -p` 子进程，流式捕获输出，等待完成。

        Parameters
        ----------
        prompt : str
            传入 `claude -p` 的 prompt 文本
        workspace : Path
            子进程 cwd；子进程创建/读取的相对路径文件都落在这里
        run_id : str, optional
            所属运行 ID，写入 CCStreamEvent.run_id；默认为空串
        timeout_sec : float, optional
            超时时间（秒）；None 则用构造函数里的 default_timeout_sec
        permission_mode : str, optional
            Claude Code `--permission-mode` 值（如 "bypassPermissions"、"acceptEdits"）。
            None 则不传此标志，使用 CLI 默认（交互确认）。ML 实验场景建议传
            "bypassPermissions"，因工作区隔离且需让 agent 自由创建文件。
        extra_args : list[str], optional
            追加给 `claude` CLI 的额外参数

        Returns
        -------
        CCResult
            包含 exit_code、stdout、stderr、耗时和 workspace

        Raises
        ------
        CCTimeoutError
            超过 timeout_sec 时抛出，子进程已被 kill
        RuntimeError
            Claude Code 二进制未找到或启动失败
        """
        workspace = Path(workspace)
        workspace.mkdir(parents=True, exist_ok=True)
        timeout = timeout_sec if timeout_sec is not None else self._default_timeout_sec

        combined_extra: list[str] = []
        if permission_mode is not None:
            combined_extra.extend(["--permission-mode", permission_mode])
        if extra_args:
            combined_extra.extend(extra_args)
        args = self._build_cli_args(prompt=prompt, extra_args=combined_extra or None)

        started = time.perf_counter()
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(workspace),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Claude Code binary not found: {args[0]}"
            ) from exc

        stdout_buf: list[str] = []
        stderr_buf: list[str] = []

        async def pump(stream: asyncio.StreamReader, channel: str, buf: list[str]) -> None:
            """从子进程流逐行读取，解码后存入 buf 并发事件。"""
            while True:
                chunk = await stream.readline()
                if not chunk:
                    break
                line = chunk.decode("utf-8", errors="replace").rstrip("\r\n")
                buf.append(line)
                self._emit(
                    CCStreamEvent(
                        ts=_now_iso(),
                        run_id=run_id,
                        channel=channel,
                        line=line,
                    )
                )

        assert process.stdout is not None and process.stderr is not None
        pump_tasks = [
            asyncio.create_task(pump(process.stdout, "stdout", stdout_buf)),
            asyncio.create_task(pump(process.stderr, "stderr", stderr_buf)),
        ]

        try:
            exit_code = await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
            for task in pump_tasks:
                task.cancel()
            for task in pump_tasks:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            duration = time.perf_counter() - started
            self._emit(
                CCStreamEvent(
                    ts=_now_iso(),
                    run_id=run_id,
                    channel="timeout",
                    line=f"Process killed after {timeout}s timeout",
                )
            )
            raise CCTimeoutError(
                f"claude -p exceeded {timeout}s timeout; process killed",
                partial_stdout="\n".join(stdout_buf),
                partial_stderr="\n".join(stderr_buf),
                duration_sec=duration,
            )

        for task in pump_tasks:
            await task

        duration = time.perf_counter() - started
        return CCResult(
            exit_code=exit_code,
            stdout="\n".join(stdout_buf),
            stderr="\n".join(stderr_buf),
            duration_sec=duration,
            workspace=workspace,
        )

    def _build_cli_args(
        self,
        *,
        prompt: str,
        extra_args: list[str] | None,
    ) -> list[str]:
        """拼接最终的子进程命令行参数。

        默认形态为 `[<claude>, -p, <prompt>, *extra_args]`。测试可通过子类覆盖
        此方法注入 fake 可执行文件，避免触发真实 CLI。
        """
        args = [self._resolve_bin(), "-p", prompt]
        if extra_args:
            args.extend(extra_args)
        return args

    def _resolve_bin(self) -> str:
        """解析二进制路径。

        若 claude_bin 是绝对路径直接返回；否则用 shutil.which 查 PATH，
        能自动处理 Windows 下的 PATHEXT（如 claude.cmd / claude.exe）。
        """
        if Path(self._claude_bin).is_absolute():
            return self._claude_bin
        resolved = shutil.which(self._claude_bin)
        if resolved is None:
            return self._claude_bin
        return resolved

    def _emit(self, event: object) -> None:
        """通过 event_sink 回调推送事件。"""
        if self._event_sink is not None:
            self._event_sink(event)


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 8601 字符串。"""
    return datetime.now(timezone.utc).isoformat()
