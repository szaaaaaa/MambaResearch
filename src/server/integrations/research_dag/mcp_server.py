"""research_dag MCP server —— stdio NDJSON。

5 个粗粒度工具
~~~~~~~~~~~~~~
* ``start(intent, constraints?, max_depth=5)`` → ``run_id``
* ``status(run_id)`` → ``{state, current_node, progress_pct, elapsed_s, error}``
* ``result(run_id)`` → ``{artifacts, summary}``（仅 completed 后调）
* ``cancel(run_id)`` → ``{ok}``（best-effort，下一 await 点生效）
* ``list_runs(project_root?, limit=50)`` → ``[{run_id, intent_preview, ...}]``

调度协议
~~~~~~~~
``_handle_tools_call`` 在 ``_main_loop`` 中**直接调用**（非 ``to_thread``），
因此可在 handler 内安全 ``asyncio.create_task``——supervisor 内部用
``asyncio.get_running_loop()`` 拿 loop 启 run task。**勿** 把 dispatch
搬到 ``to_thread``，否则 ``create_task`` 没 loop 可拿。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.server.integrations.research_dag.runtime_holder import (  # noqa: E402
    get_runtime_for_active_project,
)
from src.server.integrations.research_dag.supervisor import (  # noqa: E402
    get_supervisor,
)


SERVER_NAME = "mamba-research-dag"
SERVER_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# stdio NDJSON
# ---------------------------------------------------------------------------


def _read_message(stream: Any) -> dict[str, Any] | None:
    while True:
        line = stream.readline()
        if not line:
            return None
        stripped = line.strip()
        if not stripped:
            continue
        try:
            return json.loads(stripped.decode("utf-8"))
        except json.JSONDecodeError as exc:
            return {
                "__parse_error__": str(exc),
                "__raw__": stripped[:200].decode("utf-8", errors="replace"),
            }


def _write_message(stream: Any, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    stream.write(body + b"\n")
    stream.flush()


def _result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _tool_text_result(structured: Any) -> dict[str, Any]:
    text = json.dumps(structured, ensure_ascii=False)
    return {
        "structuredContent": structured,
        "content": [{"type": "text", "text": text}],
        "isError": False,
    }


def _tool_error_result(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


# ---------------------------------------------------------------------------
# Tool descriptors
# ---------------------------------------------------------------------------


def _tool_descriptors() -> list[dict[str, Any]]:
    return [
        {
            "name": "start",
            "description": (
                "在当前 active project 下启动一段结构化 DAG 研究任务。"
                "立即返 run_id；用 status / result / cancel 轮询。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "研究意图原文，如 \"做一次 mamba state space models 的结构化文献综述\"",
                    },
                    "constraints": {
                        "type": ["object", "null"],
                        "description": "约束 dict（预留；本版未下传给 runtime）",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "DAG 最大深度（预留；本版未下传给 runtime）",
                        "default": 5,
                    },
                },
                "required": ["intent"],
            },
        },
        {
            "name": "status",
            "description": "查询 run 的实时状态。",
            "inputSchema": {
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
            },
        },
        {
            "name": "result",
            "description": "拉取已完成 run 的产物 + 总结。state != 'completed' 时返 isError。",
            "inputSchema": {
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
            },
        },
        {
            "name": "cancel",
            "description": (
                "请求取消 run。**best-effort**：仅在 runtime 下一个 await 点生效；"
                "sync IO 段（sqlite / 文件 / mkdir）不响应。返 {ok: bool}。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
            },
        },
        {
            "name": "list_runs",
            "description": "列出本进程内的 DAG run（in-memory，重启丢失）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_root": {
                        "type": ["string", "null"],
                        "description": "按 project_root 过滤；缺省列全部",
                    },
                    "limit": {"type": "integer", "default": 50},
                },
            },
        },
    ]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def _coerce_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _call_start(args: dict[str, Any]) -> dict[str, Any]:
    intent = _coerce_str(args.get("intent"))
    if intent is None:
        return _tool_error_result("intent 必填")
    constraints = args.get("constraints")
    if constraints is not None and not isinstance(constraints, dict):
        return _tool_error_result("constraints 须为 object 或 null")
    max_depth_raw = args.get("max_depth", 5)
    try:
        max_depth = int(max_depth_raw)
    except (TypeError, ValueError):
        return _tool_error_result("max_depth 须为整数")

    runtime = get_runtime_for_active_project()
    if runtime is None:
        return _tool_error_result("当前无 active project；请先在 MambaResearch UI 选/建项目")

    from src.server.projects.registry import get_registry

    project = get_registry().get_active()
    project_root = project.path if project else None

    run_id = get_supervisor().start(
        runtime=runtime,
        intent=intent,
        constraints=constraints,
        max_depth=max_depth,
        project_root=project_root,
    )
    return _tool_text_result({"run_id": run_id})


def _resolve_run_id(args: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    run_id = _coerce_str(args.get("run_id"))
    if run_id is None:
        return None, _tool_error_result("run_id 必填")
    return run_id, None


def _call_status(args: dict[str, Any]) -> dict[str, Any]:
    run_id, err = _resolve_run_id(args)
    if err is not None:
        return err
    info = get_supervisor().status(run_id)
    if info is None:
        return _tool_error_result(f"未知 run_id：{run_id}")
    return _tool_text_result(info)


def _call_result(args: dict[str, Any]) -> dict[str, Any]:
    run_id, err = _resolve_run_id(args)
    if err is not None:
        return err
    sup = get_supervisor()
    info = sup.status(run_id)
    if info is None:
        return _tool_error_result(f"未知 run_id：{run_id}")
    if info["state"] != "completed":
        return _tool_error_result(
            f"run {run_id} 当前 state={info['state']}；只有 completed 才可拉 result"
        )
    res = sup.result(run_id)
    if res is None:
        return _tool_error_result(f"run {run_id} completed 但无 result（不应发生）")
    return _tool_text_result(res)


def _call_cancel(args: dict[str, Any]) -> dict[str, Any]:
    run_id, err = _resolve_run_id(args)
    if err is not None:
        return err
    ok = get_supervisor().cancel(run_id)
    return _tool_text_result({"ok": ok, "run_id": run_id})


def _call_list_runs(args: dict[str, Any]) -> dict[str, Any]:
    project_root = _coerce_str(args.get("project_root"))
    limit_raw = args.get("limit", 50)
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        return _tool_error_result("limit 须为整数")
    if limit < 1 or limit > 1000:
        return _tool_error_result("limit 须在 [1, 1000]")
    runs = get_supervisor().list_runs(project_root=project_root, limit=limit)
    return _tool_text_result({"runs": runs})


_TOOL_DISPATCH = {
    "start": _call_start,
    "status": _call_status,
    "result": _call_result,
    "cancel": _call_cancel,
    "list_runs": _call_list_runs,
}


# ---------------------------------------------------------------------------
# Request handlers
# ---------------------------------------------------------------------------


def _handle_initialize(msg_id: Any) -> dict[str, Any]:
    return _result(
        msg_id,
        {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "capabilities": {"tools": {}},
        },
    )


def _handle_tools_list(msg_id: Any) -> dict[str, Any]:
    return _result(msg_id, {"tools": _tool_descriptors()})


def _handle_tools_call(msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    name = str(params.get("name") or "").strip()
    arguments = params.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}

    handler = _TOOL_DISPATCH.get(name)
    if handler is None:
        return _result(
            msg_id,
            _tool_error_result(f"未知工具：{name}（可用：{sorted(_TOOL_DISPATCH)}）"),
        )

    try:
        result = handler(arguments)
    except Exception as exc:  # noqa: BLE001
        return _result(msg_id, _tool_error_result(f"工具内部错误：{exc}"))
    return _result(msg_id, result)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def _main_loop() -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    while True:
        message = await asyncio.to_thread(_read_message, stdin)
        if message is None:
            return
        if "__parse_error__" in message:
            await asyncio.to_thread(
                _write_message,
                stdout,
                _error(None, -32700, f"parse error: {message['__parse_error__']}"),
            )
            continue

        msg_id = message.get("id")
        method = str(message.get("method") or "").strip()
        params = dict(message.get("params") or {})

        try:
            if method == "initialize":
                response = _handle_initialize(msg_id)
            elif method in {"initialized", "notifications/initialized"}:
                continue
            elif method == "tools/list":
                response = _handle_tools_list(msg_id)
            elif method == "tools/call":
                # 直接同步 dispatch；handler 内 supervisor.start 会 create_task。
                response = _handle_tools_call(msg_id, params)
            else:
                response = _error(msg_id, -32601, f"method not supported: {method}")
        except Exception as exc:  # noqa: BLE001
            response = _error(msg_id, -32000, f"internal error: {exc}")

        await asyncio.to_thread(_write_message, stdout, response)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MambaResearch research_dag MCP server (stdio NDJSON JSON-RPC)",
    )
    parser.parse_args()
    asyncio.run(_main_loop())


# ---------------------------------------------------------------------------
# Claude Agent SDK 默认挂载配置
# ---------------------------------------------------------------------------

DEFAULT_SERVER_KEY = "mamba_research_dag"


def default_mcp_config(root: Path) -> dict[str, dict[str, Any]]:
    if os.environ.get("MAMBA_RESEARCH_DAG_MCP_DISABLED", "").strip() == "1":
        return {}
    resolved_root = str(root.resolve())
    return {
        DEFAULT_SERVER_KEY: {
            "type": "stdio",
            "command": sys.executable,
            "args": [
                "-m",
                "src.server.integrations.research_dag.mcp_server",
            ],
            "env": {"PYTHONPATH": resolved_root},
        },
    }


if __name__ == "__main__":
    main()
