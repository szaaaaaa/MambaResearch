from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable

from src.dynamic_os.policy.engine import PolicyEngine

CodeExecutor = Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]]


class ExecutionGateway:
    def __init__(self, *, policy: PolicyEngine, executor: CodeExecutor | None = None) -> None:
        self._policy = policy
        self._executor = executor

    async def execute_code(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_sec: int = 60,
    ) -> dict[str, Any]:
        self._policy.assert_sandbox_exec_allowed()
        if language.casefold() in {"bash", "sh", "shell", "powershell", "pwsh"}:
            self._policy.assert_command_allowed(code)
        self._policy.record_tool_invocation()
        if self._executor is None:
            raise RuntimeError("no code executor configured")
        result = self._executor(code=code, language=language, timeout_sec=timeout_sec)
        if inspect.isawaitable(result):
            return await result
        return result

