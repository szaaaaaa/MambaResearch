"""MCP sandbox direct-call（Stage 3 Task 3）。

让前端直接对一个 MCP tool 跑一次 ``tools/call``——不经过 Claude / Codex。
开发新 MCP server 与排查 tool schema 必备。

实现方式与 ``probe.py`` 一致：每次调用 spawn 一个短生命 stdio subprocess，跑
``initialize → tools/call → 关闭``。每次调用独立隔离：因为 sandbox 调用的频率
天然低（人工触发），相比维持长连接的复杂度，开销可以忽略。

危险标记
~~~~~~~~
``DANGEROUS_TOOLS`` 是手维护的 ``set[(server, tool)]``。在此列表里的工具调用
要求 client 显式传 ``confirm=True``，否则返 ``need_confirm`` 错。本仓库当前
所有 builtin server tool 都不在表中（mamba_workspace 仅写本地 DB；
research_agent 的危险性由 dynamic_os 内部 policy 控）；机制留作未来用户接入
带 shell exec / fs write / 外发 HTTP 的第三方 server 时的护栏。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from src.server.mcp.models import McpServerInfo


DEFAULT_CALL_TIMEOUT_S = 30.0

# (server_name, tool_name) 二元组——见模块注释
DANGEROUS_TOOLS: set[tuple[str, str]] = set()


class SandboxResult:
    __slots__ = (
        "output",
        "is_error",
        "error",
        "duration_ms",
        "raw_response",
    )

    def __init__(
        self,
        *,
        output: Any = None,
        is_error: bool = False,
        error: str | None = None,
        duration_ms: int = 0,
        raw_response: dict[str, Any] | None = None,
    ) -> None:
        self.output = output
        self.is_error = is_error
        self.error = error
        self.duration_ms = duration_ms
        self.raw_response = raw_response

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "is_error": self.is_error,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


def is_dangerous(server_name: str, tool_name: str) -> bool:
    return (server_name, tool_name) in DANGEROUS_TOOLS


async def call_tool(
    server: McpServerInfo,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    timeout_s: float = DEFAULT_CALL_TIMEOUT_S,
    extra_env: dict[str, str] | None = None,
) -> SandboxResult:
    """对单个 tool 跑一次 sandbox 调用。

    Parameters
    ----------
    server : McpServerInfo
        registry 拿到的 server 元信息。
    tool_name : str
        tool 短名（不带 ``mcp__<server>__`` 前缀）。
    arguments : dict
        ``tools/call`` params.arguments，按 server 的 inputSchema。
    """
    started = time.time()
    if server.transport != "stdio":
        return SandboxResult(
            is_error=True,
            error=f"transport {server.transport!r} sandbox 未实现（仅 stdio）",
            duration_ms=int((time.time() - started) * 1000),
        )
    if not server.command:
        return SandboxResult(
            is_error=True,
            error="config 缺 command 字段",
            duration_ms=int((time.time() - started) * 1000),
        )

    env = os.environ.copy()
    env.update(server.env)
    if extra_env:
        env.update(extra_env)

    try:
        response = await asyncio.wait_for(
            _run_tool_call_subprocess(server.command, server.args, env, tool_name, arguments),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        return SandboxResult(
            is_error=True,
            error=f"sandbox call 超时（>{timeout_s}s）",
            duration_ms=int((time.time() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001
        return SandboxResult(
            is_error=True,
            error=f"sandbox 调用异常：{exc}",
            duration_ms=int((time.time() - started) * 1000),
        )

    duration_ms = int((time.time() - started) * 1000)

    if "error" in response:
        err = response["error"]
        return SandboxResult(
            is_error=True,
            error=err.get("message") if isinstance(err, dict) else str(err),
            duration_ms=duration_ms,
            raw_response=response,
        )

    result = response.get("result") or {}
    # MCP 规范：tools/call 的返回 ``result`` 含 ``content`` 与可选 ``isError``、
    # ``structuredContent``。把 isError 显式转成 SandboxResult.is_error。
    is_err = bool(result.get("isError"))
    output = result.get("structuredContent")
    if output is None:
        output = result.get("content")
    error_text = None
    if is_err:
        # content 数组里的 text 字段拼出错误描述
        content = result.get("content") or []
        parts = [
            blk.get("text")
            for blk in content
            if isinstance(blk, dict) and isinstance(blk.get("text"), str)
        ]
        error_text = "\n".join(p for p in parts if p) or "tool reported isError"

    return SandboxResult(
        output=output,
        is_error=is_err,
        error=error_text,
        duration_ms=duration_ms,
        raw_response=response,
    )


async def _run_tool_call_subprocess(
    command: str,
    args: list[str],
    env: dict[str, str],
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        command,
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
    }
    call_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }

    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write((json.dumps(init_req) + "\n").encode("utf-8"))
        proc.stdin.write((json.dumps(call_req) + "\n").encode("utf-8"))
        await proc.stdin.drain()

        init_resp: dict[str, Any] | None = None
        call_resp: dict[str, Any] | None = None
        while init_resp is None or call_resp is None:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line.decode("utf-8").strip())
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            mid = msg.get("id")
            if mid == 1:
                init_resp = msg
            elif mid == 2:
                call_resp = msg

        if call_resp is None:
            return {
                "error": {
                    "code": -1,
                    "message": "no tools/call response",
                }
            }
        return call_resp
    finally:
        try:
            if proc.stdin is not None and not proc.stdin.is_closing():
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
