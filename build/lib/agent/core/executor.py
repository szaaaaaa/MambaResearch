from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol


@dataclass
class TaskRequest:
    """Structured task emitted by node logic."""

    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    timeout_sec: float = 120.0


@dataclass
class TaskResult:
    """Structured executor result."""

    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class Executor(Protocol):
    """Executor contract."""

    def supported_actions(self) -> List[str]:
        ...

    def execute(self, task: TaskRequest, cfg: Dict[str, Any]) -> TaskResult:
        ...

