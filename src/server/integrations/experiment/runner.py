"""单脚本本地实验子进程管理器。

设计要点
~~~~~~~~
* **独立 process group**：Windows 用 ``CREATE_NEW_PROCESS_GROUP``，Unix 用
  ``start_new_session=True``——这样 ``cancel()`` 能 kill 整个进程树（包括
  脚本起的子进程，比如 PyTorch DataLoader workers）
* **后台 reader 线程**：每个 run 启一个 daemon thread 读 stdout，把
  ``[[METRIC]] {...}`` 行解析为 metric，其他行 append 到 ring-style log buffer
* **进程级单例 ExperimentRunner**：MCP server 每次 ``tools/call`` 复用同一个
  runner，所以跨 tool 调用的 run_id 仍可查
* **薄持久化**：run 启动时往 ``experiment_runs`` 表写一行 ``running``；done /
  error / cancelled 时 update 同一行；metrics / logs 不入库（频次太高，留内存）
"""
from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


METRIC_LINE_PREFIX = "[[METRIC]]"
LOG_BUFFER_MAX_LINES = 5000


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class MetricSample:
    step: int
    name: str
    value: float
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "name": self.name,
            "value": self.value,
            "timestamp": self.timestamp,
        }


@dataclass
class ExperimentRun:
    """单个 experiment run 的内存状态。"""

    id: str
    script_path: str
    args: list[str]
    env: dict[str, str]
    cwd: str
    started_at: float
    proc: Any  # subprocess.Popen，测试时 fake
    status: str = "running"
    exit_code: int | None = None
    ended_at: float | None = None
    pid: int | None = None
    log_lines: list[str] = field(default_factory=list)
    metrics: list[MetricSample] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _reader: threading.Thread | None = None

    def append_log(self, line: str) -> None:
        with self._lock:
            self.log_lines.append(line)
            if len(self.log_lines) > LOG_BUFFER_MAX_LINES:
                # ring buffer：截首段
                drop = len(self.log_lines) - LOG_BUFFER_MAX_LINES
                del self.log_lines[:drop]

    def tail_log(self, n: int) -> list[str]:
        with self._lock:
            return list(self.log_lines[-max(n, 0):])

    def add_metric(self, sample: MetricSample) -> None:
        with self._lock:
            self.metrics.append(sample)

    def all_metrics(self) -> list[MetricSample]:
        with self._lock:
            return list(self.metrics)

    def last_metric(self) -> MetricSample | None:
        with self._lock:
            return self.metrics[-1] if self.metrics else None


# ---------------------------------------------------------------------------
# 子进程 spawn helper（Windows/Unix 平台分支）
# ---------------------------------------------------------------------------


def _spawn_kwargs() -> dict[str, Any]:
    """returns kwargs for ``subprocess.Popen`` to create a new process group."""
    if sys.platform == "win32":
        # CREATE_NEW_PROCESS_GROUP = 0x00000200，允许 Ctrl+Break / TerminateProcess
        return {"creationflags": 0x00000200}
    return {"start_new_session": True}


def _terminate_process(proc: Any) -> None:
    """跨平台终止进程组：先 SIGTERM，1s 后 SIGKILL。"""
    try:
        if sys.platform == "win32":
            # Windows 没有 SIGTERM 概念；CREATE_NEW_PROCESS_GROUP 后可发 CTRL_BREAK_EVENT
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            except Exception:
                proc.terminate()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        pass
    try:
        proc.wait(timeout=1.0)
        return
    except Exception:
        pass
    # 强杀
    try:
        if sys.platform == "win32":
            proc.kill()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _now() -> float:
    return time.time()


def _redact_env(env: dict[str, str]) -> dict[str, str]:
    """敏感字段 redact（mcp_calls 写库时也用同样规则）。"""
    redacted: dict[str, str] = {}
    for k, v in env.items():
        kl = k.lower()
        if "key" in kl or "token" in kl or "secret" in kl or "password" in kl:
            redacted[k] = "<redacted>"
        else:
            redacted[k] = v
    return redacted


def _parse_metric_line(raw: str) -> MetricSample | None:
    """解析 ``[[METRIC]] {...}`` 行；非合规行返 None。"""
    idx = raw.find(METRIC_LINE_PREFIX)
    if idx < 0:
        return None
    payload = raw[idx + len(METRIC_LINE_PREFIX):].strip()
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    name = obj.get("name")
    value = obj.get("value")
    step = obj.get("step", 0)
    if not isinstance(name, str) or not isinstance(value, (int, float)):
        return None
    return MetricSample(
        step=int(step) if isinstance(step, (int, float)) else 0,
        name=name,
        value=float(value),
        timestamp=_now(),
    )


class ExperimentRunner:
    """进程级 runner——管理所有活跃 + 已完成 ExperimentRun。"""

    def __init__(self, *, popen: Any = None, db_factory: Any = None) -> None:
        # 注入 subprocess.Popen 的位置便于测试 mock
        self._popen = popen or subprocess.Popen
        self._db_factory = db_factory  # 缺省 None → 不持久化（测试默认）
        self._runs: dict[str, ExperimentRun] = {}
        self._lock = threading.Lock()

    # -------- 运维 ------------------------------------------------------

    def get(self, run_id: str) -> ExperimentRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def list_active(self) -> list[ExperimentRun]:
        with self._lock:
            return [r for r in self._runs.values() if r.status == "running"]

    # -------- start -----------------------------------------------------

    def start(
        self,
        script_path: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        *,
        project_id: str | None = None,
        conversation_id: str | None = None,
        segment_id: str | None = None,
        cli_session_id: str | None = None,
    ) -> ExperimentRun:
        """启动一个本地 Python 脚本子进程。

        Returns
        -------
        ExperimentRun
            已注册到内存，子进程已 spawn。``proc`` 字段持有 ``subprocess.Popen``
            （或测试 fake）。
        """
        path = Path(script_path)
        if not path.exists():
            raise FileNotFoundError(f"script not found: {script_path}")
        run_id = uuid.uuid4().hex[:16]
        clean_args = list(args or [])
        run_env = dict(os.environ)
        if env:
            run_env.update({str(k): str(v) for k, v in env.items()})
        run_cwd = cwd or str(path.parent)
        cmd = [sys.executable, str(path), *clean_args]

        proc = self._popen(
            cmd,
            cwd=run_cwd,
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True,
            **_spawn_kwargs(),
        )

        run = ExperimentRun(
            id=run_id,
            script_path=str(path),
            args=clean_args,
            env=_redact_env(env or {}),
            cwd=run_cwd,
            started_at=_now(),
            proc=proc,
            pid=getattr(proc, "pid", None),
        )
        with self._lock:
            self._runs[run_id] = run

        # 持久化登记（best-effort，不阻塞）
        if self._db_factory is not None:
            try:
                self._persist_start(
                    run,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    segment_id=segment_id,
                    cli_session_id=cli_session_id,
                )
            except Exception:
                pass

        # 后台读 stdout
        t = threading.Thread(target=self._reader_loop, args=(run,), daemon=True)
        run._reader = t
        t.start()
        return run

    # -------- status / logs / metrics ----------------------------------

    def status(self, run_id: str) -> dict[str, Any] | None:
        run = self.get(run_id)
        if run is None:
            return None
        last = run.last_metric()
        elapsed = (run.ended_at or _now()) - run.started_at
        return {
            "run_id": run.id,
            "status": run.status,
            "exit_code": run.exit_code,
            "pid": run.pid,
            "script_path": run.script_path,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
            "elapsed_s": round(elapsed, 3),
            "log_lines": len(run.log_lines),
            "metrics_count": len(run.all_metrics()),
            "last_metric": last.to_dict() if last else None,
        }

    def logs(self, run_id: str, tail: int = 200) -> list[str] | None:
        run = self.get(run_id)
        if run is None:
            return None
        return run.tail_log(tail)

    def metrics(self, run_id: str) -> list[dict[str, Any]] | None:
        run = self.get(run_id)
        if run is None:
            return None
        return [m.to_dict() for m in run.all_metrics()]

    # -------- cancel ----------------------------------------------------

    def cancel(self, run_id: str) -> bool:
        run = self.get(run_id)
        if run is None:
            return False
        if run.status != "running":
            return False
        _terminate_process(run.proc)
        # reader_loop 会观察到进程退出，写状态 cancelled
        run.status = "cancelled"
        run.ended_at = _now()
        if self._db_factory is not None:
            try:
                self._persist_end(run)
            except Exception:
                pass
        return True

    # -------- 内部 ------------------------------------------------------

    def _reader_loop(self, run: ExperimentRun) -> None:
        """读子进程 stdout 直到 EOF，分发到 log_buffer / metrics。"""
        proc = run.proc
        stdout = getattr(proc, "stdout", None)
        if stdout is None:
            return
        try:
            for raw in stdout:
                if raw is None:
                    break
                line = raw.rstrip("\n")
                metric = _parse_metric_line(line)
                if metric is not None:
                    run.add_metric(metric)
                    # 同时把 metric 行也存到 log（让用户看见）
                run.append_log(line)
        except Exception as exc:  # noqa: BLE001
            run.append_log(f"[reader-loop-error] {exc}")
        finally:
            # 等待 proc 退出 + 标记最终状态
            try:
                proc.wait()
            except Exception:
                pass
            if run.status == "running":
                exit_code = getattr(proc, "returncode", None)
                run.exit_code = exit_code
                run.ended_at = _now()
                run.status = "done" if exit_code == 0 else "error"
                if self._db_factory is not None:
                    try:
                        self._persist_end(run)
                    except Exception:
                        pass

    def _persist_start(
        self,
        run: ExperimentRun,
        *,
        project_id: str | None,
        conversation_id: str | None,
        segment_id: str | None,
        cli_session_id: str | None,
    ) -> None:
        db = self._db_factory()
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO experiment_runs(
                    id, project_id, conversation_id, segment_id, cli_session_id,
                    script_path, args_json, env_json, cwd,
                    status, pid, exit_code, started_at, ended_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, NULL, ?, NULL)
                """,
                (
                    run.id,
                    project_id,
                    conversation_id,
                    segment_id,
                    cli_session_id,
                    run.script_path,
                    json.dumps(run.args),
                    json.dumps(run.env),
                    run.cwd,
                    run.pid,
                    int(run.started_at),
                ),
            )

    def _persist_end(self, run: ExperimentRun) -> None:
        db = self._db_factory()
        with db.cursor() as cur:
            cur.execute(
                """
                UPDATE experiment_runs
                   SET status=?, exit_code=?, ended_at=?
                 WHERE id=?
                """,
                (
                    run.status,
                    run.exit_code,
                    int(run.ended_at) if run.ended_at else None,
                    run.id,
                ),
            )


# ---------------------------------------------------------------------------
# 进程级单例
# ---------------------------------------------------------------------------


_RUNNER: ExperimentRunner | None = None
_RUNNER_LOCK = threading.Lock()


def get_runner() -> ExperimentRunner:
    """进程级单例。MCP server 每次 ``tools/call`` 复用同一个 runner。"""
    global _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is None:
            _RUNNER = ExperimentRunner()
        return _RUNNER


def reset_runner_for_tests(runner: ExperimentRunner | None = None) -> None:
    """测试 helper：注入 fake runner。"""
    global _RUNNER
    with _RUNNER_LOCK:
        _RUNNER = runner


# ---------------------------------------------------------------------------
# 兼容性导出
# ---------------------------------------------------------------------------

__all__ = [
    "ExperimentRunner",
    "ExperimentRun",
    "MetricSample",
    "METRIC_LINE_PREFIX",
    "get_runner",
    "reset_runner_for_tests",
    "_parse_metric_line",
    "_redact_env",
]


# 暴露给 shlex 用法（旧 API 兼容）；非主路径，留 utility
def quote_args(args: list[str]) -> str:
    return shlex.join(args)
