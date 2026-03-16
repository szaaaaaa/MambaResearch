from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable

from src.dynamic_os.policy.engine import PolicyEngine
from src.dynamic_os.tools.gateway.mcp import McpGateway
from src.dynamic_os.tools.registry import ToolCapability

CodeExecutor = Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]]


class ExecutionGateway:
    def __init__(
        self,
        *,
        policy: PolicyEngine,
        mcp: McpGateway | None = None,
        executor: CodeExecutor | None = None,
    ) -> None:
        self._policy = policy
        self._mcp = mcp
        self._executor = executor

    async def execute_code(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_sec: int = 60,
        remote: bool = False,
    ) -> dict[str, Any]:
        if remote:
            self._policy.assert_remote_exec_allowed()
        else:
            self._policy.assert_sandbox_exec_allowed()
        if language.casefold() in {"bash", "sh", "shell", "powershell", "pwsh"}:
            self._policy.assert_command_allowed(code)
        if self._executor is not None:
            self._policy.record_tool_invocation()
            result = self._executor(code=code, language=language, timeout_sec=timeout_sec)
            if inspect.isawaitable(result):
                return await result
            return result
        if self._mcp is not None:
            preferred = "remote_execute_code" if remote else "execute_code"
            return await self._mcp.invoke_capability(
                ToolCapability.execute_code,
                {
                    "code": code,
                    "language": language,
                    "timeout_sec": timeout_sec,
                },
                preferred=preferred,
            )
        raise RuntimeError("no code executor configured")
