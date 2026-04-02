"""代码执行网关模块 — 提供沙箱和远程代码执行能力。

本模块封装了代码执行的权限校验和调用逻辑：
- 本地沙箱执行：在受限环境中运行代码
- 远程执行：将代码发送到远程执行环境

执行前会通过策略引擎校验执行权限（sandbox_exec / remote_exec），
并对 shell 类语言额外校验命令安全性。
支持通过自定义 CodeExecutor 回调函数或 MCP 网关两种执行方式。
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable

from src.dynamic_os.policy.engine import PolicyEngine
from src.dynamic_os.tools.gateway.mcp import McpGateway
from src.dynamic_os.tools.registry import ToolCapability

# CodeExecutor 类型：自定义代码执行器回调，支持同步/异步
CodeExecutor = Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]]


class ExecutionGateway:
    """代码执行网关 — 统一管理沙箱和远程代码执行。

    优先使用注入的 CodeExecutor 回调执行代码；如果未配置，
    则回退到 MCP 网关调用 exec 服务器。
    """

    def __init__(
        self,
        *,
        policy: PolicyEngine,
        mcp: McpGateway | None = None,
        executor: CodeExecutor | None = None,
    ) -> None:
        self._policy = policy      # 策略引擎，校验执行权限
        self._mcp = mcp            # MCP 网关（备选执行通道）
        self._executor = executor  # 自定义代码执行器（优先使用）

    async def execute_code(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_sec: int = 60,
        remote: bool = False,
    ) -> dict[str, Any]:
        """执行代码并返回结果。

        参数
        ----------
        code : str
            要执行的代码字符串。
        language : str, optional
            编程语言，默认 "python"。
        timeout_sec : int, optional
            执行超时时间（秒），默认 60。
        remote : bool, optional
            是否使用远程执行环境，默认 False。

        返回
        -------
        dict[str, Any]
            执行结果，通常包含 exit_code、stdout、stderr 等字段。

        异常
        ------
        PolicyViolationError
            当执行权限被策略禁止时抛出。
        RuntimeError
            当未配置任何执行器时抛出。
        """
        # 根据执行模式校验对应权限
        if remote:
            self._policy.assert_remote_exec_allowed()
        else:
            self._policy.assert_sandbox_exec_allowed()
        # 对 shell 类语言额外校验命令安全性
        if language.casefold() in {"bash", "sh", "shell", "powershell", "pwsh"}:
            self._policy.assert_command_allowed(code)
        # 优先使用自定义执行器
        if self._executor is not None:
            self._policy.record_tool_invocation()
            result = self._executor(code=code, language=language, timeout_sec=timeout_sec)
            # 兼容同步和异步执行器
            if inspect.isawaitable(result):
                return await result
            return result
        # 回退到 MCP 网关
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
