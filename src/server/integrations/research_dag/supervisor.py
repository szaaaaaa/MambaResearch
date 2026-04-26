"""DAG run 后台 supervisor——管理多个并发 run 的生命周期。

每个 run = 一个 ``asyncio.Task``，包装 ``DynamicResearchRuntime.run``。
``start`` 立即返 ``run_id``，调用方不阻塞；后续通过 ``status`` / ``result`` /
``cancel`` 轮询。进程级单例（:func:`get_supervisor`）。

设计要点
~~~~~~~~
* **不持久化**：本 stage 只 in-memory dict；DB 持久化（``dag_runs`` 表）
  留 Task 3 实施。重启 MCP server 即丢失 run 历史。
* **cancel 是 best-effort**：``asyncio.Task.cancel()`` 只在下一个 await
  点生效；runtime 内部有大段 sync IO（sqlite / file / mkdir）不响应。
  ``state == 'cancelled'`` 表示"已请求取消"，不保证子进程 / 文件操作已停止。
* **不依赖 holder**：``start`` 接 ``runtime`` 入参；MCP 工具 handler 从
  holder 拿 runtime 后传入。这样测试可注入 FakeRuntime，无需 monkeypatch。
"""
from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.dynamic_os.runtime import DynamicResearchRuntime


VALID_STATES = frozenset({"running", "completed", "failed", "cancelled"})


@dataclass
class RunState:
    """单个 run 的可观察状态。"""

    run_id: str
    intent: str
    state: str  # 'running' | 'completed' | 'failed' | 'cancelled'
    started_at: float
    ended_at: float | None = None
    current_node: str | None = None
    progress_pct: float = 0.0
    error: str | None = None
    # ``{artifacts: list, summary: str}``——仅 completed 时有值
    result: dict[str, Any] | None = None
    project_root: str | None = None
    constraints: dict[str, Any] | None = None
    max_depth: int = 5
    _task: asyncio.Task[Any] | None = field(default=None, repr=False)

    def to_status_dict(self) -> dict[str, Any]:
        end = self.ended_at if self.ended_at is not None else time.time()
        return {
            "run_id": self.run_id,
            "state": self.state,
            "current_node": self.current_node,
            "progress_pct": self.progress_pct,
            "elapsed_s": end - self.started_at,
            "error": self.error,
        }

    def to_list_entry(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "intent_preview": self.intent[:120],
            "state": self.state,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "project_root": self.project_root,
        }


class RunSupervisor:
    """DAG run 生命周期管理。线程安全；MCP server 单进程内并发安全。"""

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}
        self._lock = Lock()

    def start(
        self,
        *,
        runtime: "DynamicResearchRuntime",
        intent: str,
        constraints: dict[str, Any] | None = None,
        max_depth: int = 5,
        project_root: str | None = None,
    ) -> str:
        """spawn 一个 run，立即返 ``run_id``；不阻塞调用方。

        必须在 asyncio loop 线程内调用——内部用 ``asyncio.get_running_loop()``
        拿 loop 启 task。

        Parameters
        ----------
        runtime
            ``DynamicResearchRuntime`` 实例；调用方负责从 holder 拿。
        intent
            用户原始研究问题；作为 ``runtime.run(user_request=...)`` 入参。
        constraints, max_depth
            预留字段——本 stage 不下传给 runtime（runtime 接口不接），仅
            存到 ``RunState`` 用于 list_runs / debug。
        project_root
            可选；用于 list_runs 按 project 过滤。
        """
        run_id = f"dag_{secrets.token_hex(6)}"
        state = RunState(
            run_id=run_id,
            intent=intent,
            state="running",
            started_at=time.time(),
            project_root=project_root,
            constraints=constraints,
            max_depth=max_depth,
        )
        loop = asyncio.get_running_loop()
        state._task = loop.create_task(self._wrap_run(state, runtime))
        with self._lock:
            self._runs[run_id] = state
        return run_id

    async def _wrap_run(
        self,
        state: RunState,
        runtime: "DynamicResearchRuntime",
    ) -> None:
        """runtime.run() 的 try/except 包装；翻译 runtime status 到我们的状态机。"""
        try:
            result = await runtime.run(user_request=state.intent, run_id=state.run_id)
            artifacts_list: list[dict[str, Any]] = []
            for art in result.artifacts or []:
                if isinstance(art, dict):
                    artifacts_list.append(dict(art))
            state.result = {
                "artifacts": artifacts_list,
                "summary": result.report_text or "",
            }
            # runtime 自身 status: completed / failed / stopped → 我们映成 completed/failed
            state.state = "completed" if result.status == "completed" else "failed"
            if state.state == "failed":
                state.error = f"runtime status: {result.status}"
            state.progress_pct = 100.0
        except asyncio.CancelledError:
            state.state = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001
            state.state = "failed"
            state.error = f"{type(exc).__name__}: {exc}"
        finally:
            state.ended_at = time.time()

    def status(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._runs.get(run_id)
        return state.to_status_dict() if state else None

    def result(self, run_id: str) -> dict[str, Any] | None:
        """已完成 run → result dict；未完成 / 未知 → None。

        调用方应先调 :meth:`status` 确认 ``state == 'completed'``。
        本方法不阻塞。
        """
        with self._lock:
            state = self._runs.get(run_id)
        if state is None or state.result is None:
            return None
        return state.result

    def cancel(self, run_id: str) -> bool:
        """请求取消；**best-effort**（仅在下一个 await 点生效）。

        Returns
        -------
        bool
            True = 取消请求已发；run 不存在或已终止 → False。
        """
        with self._lock:
            state = self._runs.get(run_id)
        if state is None:
            return False
        if state._task is None or state._task.done():
            return False
        state._task.cancel()
        return True

    def list_runs(
        self,
        *,
        project_root: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._lock:
            entries = list(self._runs.values())
        if project_root is not None:
            entries = [s for s in entries if s.project_root == project_root]
        entries.sort(key=lambda s: s.started_at, reverse=True)
        return [s.to_list_entry() for s in entries[:limit]]

    def reset_for_tests(self) -> None:
        with self._lock:
            tasks = [s._task for s in self._runs.values() if s._task is not None and not s._task.done()]
            self._runs.clear()
        for task in tasks:
            task.cancel()


# ---------------------------------------------------------------------------
# 进程级单例
# ---------------------------------------------------------------------------


_SUPERVISOR: RunSupervisor | None = None
_SUPERVISOR_LOCK = Lock()


def get_supervisor() -> RunSupervisor:
    global _SUPERVISOR
    with _SUPERVISOR_LOCK:
        if _SUPERVISOR is None:
            _SUPERVISOR = RunSupervisor()
        return _SUPERVISOR


def reset_supervisor_for_tests(supervisor: RunSupervisor | None = None) -> None:
    """清空当前 supervisor（含取消所有 in-flight task），可选注入新实例。"""
    global _SUPERVISOR
    with _SUPERVISOR_LOCK:
        if _SUPERVISOR is not None:
            _SUPERVISOR.reset_for_tests()
        _SUPERVISOR = supervisor
