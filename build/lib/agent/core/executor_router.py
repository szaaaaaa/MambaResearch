from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List

from src.agent.core.events import emit_event
from src.agent.core.executor import Executor, TaskRequest, TaskResult
from src.agent.core.failure import classify_failure

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_EXECUTORS: List[Executor] = []


def register_executor(executor: Executor) -> None:
    """Register an executor once by class type."""
    with _LOCK:
        if any(type(existing) is type(executor) for existing in _EXECUTORS):
            return
        _EXECUTORS.append(executor)


def _ensure_bootstrapped() -> None:
    from src.agent.plugins.bootstrap import ensure_plugins_registered

    ensure_plugins_registered()


def dispatch(task: TaskRequest, cfg: Dict[str, Any] | None = None) -> TaskResult:
    """Route a task to the first executor that supports task.action."""
    _ensure_bootstrapped()
    cfg = cfg or {}

    with _LOCK:
        executors = list(_EXECUTORS)

    for executor in executors:
        try:
            if task.action in executor.supported_actions():
                logger.info("Dispatching action '%s' to %s", task.action, type(executor).__name__)
                return executor.execute(task, cfg)
        except Exception as exc:  # pragma: no cover - defensive guard
            action = classify_failure(exc, context=f"executor_dispatch:{task.action}")
            emit_event(
                cfg,
                {
                    "event": "failure_routed",
                    "context": f"executor_dispatch:{task.action}",
                    "executor": type(executor).__name__,
                    "exception": type(exc).__name__,
                    "error": str(exc),
                    "action": action.value,
                },
            )
            return TaskResult(success=False, error=str(exc), metadata={"failure_action": action.value})

    return TaskResult(success=False, error=f"No executor registered for action '{task.action}'")
