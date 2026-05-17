"""MCP server status probe（Stage 3 Task 1）。

启动一个**短生命** stdio subprocess，跑一遍 ``initialize → tools/list``，把结果
打包成 ``McpServerStatus`` 返回；本模块不维持长连接，每次调用都是新进程。

为什么不复用 Claude SDK 启的 server？
-----------------------------------
SDK 启的 server 与 client 端绑死——独立从外部观测它需要侵入 SDK 内部。
ping 短生命子进程虽然有少量启动开销，但完全隔离、易于维护，并且与 ``sandbox``
模块（Stage 3 Task 3）共用启动栈。

http/sse 的 probe 走 HTTP HEAD/GET，不 spawn 进程；本模块 stage3-T1 仅实现 stdio，
http/sse 留待后续 server 真接入时实现。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from src.server.mcp.models import McpServerInfo, McpServerStatus, McpToolInfo


DEFAULT_PROBE_TIMEOUT_S = 5.0


async def probe_server(
    server: McpServerInfo,
    *,
    timeout_s: float = DEFAULT_PROBE_TIMEOUT_S,
    extra_env: dict[str, str] | None = None,
) -> McpServerStatus:
    """对单个 server 执行 initialize + tools/list 探活。

    Parameters
    ----------
    server : McpServerInfo
        registry 里的 server 元信息。
    timeout_s : float
        子进程总超时（含启动 + 两次 RPC）。超时返回 ``unreachable``。
    extra_env : dict[str, str] or None
        测试可以注入额外 env（如 ``MAMBA_ACTIVE_PROJECT_PATH``）；生产路径
        默认继承父 env，不需此参数。
    """
    started = time.time()
    if server.transport != "stdio":
        return McpServerStatus(
            server_name=server.name,
            status="error",
            tools_count=0,
            error=f"transport {server.transport!r} probe 未实现（Stage 3 仅 stdio）",
            last_ping_at=int(started),
        )

    if not server.command:
        return McpServerStatus(
            server_name=server.name,
            status="error",
            tools_count=0,
            error="config 缺 command 字段",
            last_ping_at=int(started),
        )

    env = os.environ.copy()
    env.update(server.env)
    if extra_env:
        env.update(extra_env)

    try:
        result = await asyncio.wait_for(
            _run_probe_subprocess(server.command, server.args, env=env),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        return McpServerStatus(
            server_name=server.name,
            status="unreachable",
            tools_count=0,
            error=f"probe 超时（>{timeout_s}s）",
            last_ping_at=int(started),
            duration_ms=int((time.time() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001
        return McpServerStatus(
            server_name=server.name,
            status="error",
            tools_count=0,
            error=f"probe 异常：{exc}",
            last_ping_at=int(started),
            duration_ms=int((time.time() - started) * 1000),
        )

    duration_ms = int((time.time() - started) * 1000)
    if "error" in result:
        return McpServerStatus(
            server_name=server.name,
            status="error",
            tools_count=0,
            error=str(result["error"]),
            last_ping_at=int(started),
            duration_ms=duration_ms,
        )

    raw_tools = result.get("tools") or []
    tools = [
        McpToolInfo(
            server_name=server.name,
            name=str(t.get("name") or ""),
            description=t.get("description"),
            input_schema=t.get("inputSchema") or {},
        )
        for t in raw_tools
        if isinstance(t, dict)
    ]
    return McpServerStatus(
        server_name=server.name,
        status="running",
        tools_count=len(tools),
        tools=tools,
        last_ping_at=int(started),
        duration_ms=duration_ms,
    )


async def _run_probe_subprocess(
    command: str,
    args: list[str],
    *,
    env: dict[str, str],
) -> dict[str, Any]:
    """spawn → 写两条 JSON-RPC 请求 → 读到匹配 id 的两条响应 → 关闭。

    Returns
    -------
    dict
        ``{"tools": [...]}`` 成功；``{"error": "..."}`` 协议失败。
    """
    proc = await asyncio.create_subprocess_exec(
        command,
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    # MCP spec 要求 initialize.params 含 protocolVersion + capabilities + clientInfo。
    # 我们 builtin server 的手写 _handle_initialize 不校验 clientInfo，但严格走
    # MCP SDK 的上游 server（如 paper_search_mcp）会用 pydantic ClientRequest 校验
    # 整个 schema，缺 clientInfo 直接 -32602 Invalid request parameters。
    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mambaresearch-probe", "version": "1.0.0"},
        },
    }
    list_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    }

    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write((json.dumps(init_req) + "\n").encode("utf-8"))
        proc.stdin.write((json.dumps(list_req) + "\n").encode("utf-8"))
        await proc.stdin.drain()

        # 读两条响应——按 id 匹配。stderr 收集做 error 兜底。
        init_resp: dict[str, Any] | None = None
        list_resp: dict[str, Any] | None = None
        while init_resp is None or list_resp is None:
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
                list_resp = msg

        if list_resp is None:
            stderr = await _drain_stderr(proc)
            return {"error": f"no tools/list response (stderr: {stderr[:300]})"}

        if "error" in list_resp:
            err = list_resp["error"]
            return {"error": err.get("message") if isinstance(err, dict) else str(err)}

        result = list_resp.get("result") or {}
        return {"tools": result.get("tools") or []}
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


async def _drain_stderr(proc: asyncio.subprocess.Process) -> str:
    if proc.stderr is None:
        return ""
    try:
        data = await asyncio.wait_for(proc.stderr.read(), timeout=0.5)
    except asyncio.TimeoutError:
        return ""
    return data.decode("utf-8", errors="replace")
