"""Experiment MCP server —— stdio NDJSON。

工具
~~~~
- ``run_local(script_path, args?, env?, cwd?)`` → ``run_id``
- ``status(run_id)`` → 状态 + last metric + elapsed
- ``logs(run_id, tail?)`` → 字符串列表
- ``metrics(run_id)`` → 全量 metrics 列表
- ``cancel(run_id)`` → ``{ok}``

子进程协议（stdout）：
- 任意行包含 ``[[METRIC]] {"name":..., "value":..., "step":...}`` → 入 metrics
- 其他行 → 入 log buffer
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

from src.server.integrations.experiment.runner import get_runner  # noqa: E402


SERVER_NAME = "mamba-experiment"
SERVER_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# stdio NDJSON（与其他 MCP 同形）
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
            "name": "run_local",
            "description": (
                "异步启动本地 Python 脚本子进程。立即返回 run_id；后续用 "
                "status / logs / metrics / cancel 轮询。子进程独立 process group，"
                "cancel 时杀整个进程树。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "script_path": {"type": "string", "description": "脚本绝对路径"},
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "命令行参数列表",
                    },
                    "env": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "追加 env（覆盖父进程同名 key）",
                    },
                    "cwd": {
                        "type": ["string", "null"],
                        "description": "工作目录；缺省为脚本所在目录",
                    },
                },
                "required": ["script_path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "status",
            "description": "查询 run 状态：running / done / error / cancelled + exit_code + 最近 metric。",
            "inputSchema": {
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "logs",
            "description": "取 run 的最近 N 行输出（stdout+stderr 合并）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "tail": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 200},
                },
                "required": ["run_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "metrics",
            "description": (
                "取 run 全量 metric 样本（每行 ``[[METRIC]] {...}`` 解析得到）。"
                "返回顺序与 stdout 出现顺序一致。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "cancel",
            "description": "终止 run 子进程组。已结束的 run 返回 ok=False。",
            "inputSchema": {
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
        },
    ]


# ---------------------------------------------------------------------------
# Tool 调用
# ---------------------------------------------------------------------------


def _coerce_str(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    s = v.strip()
    return s or None


def _call_run_local(args: dict[str, Any]) -> dict[str, Any]:
    script = _coerce_str(args.get("script_path"))
    if script is None:
        return _tool_error_result("script_path 必填")
    raw_args = args.get("args") or []
    if not isinstance(raw_args, list) or any(not isinstance(a, str) for a in raw_args):
        return _tool_error_result("args 必须是字符串数组")
    raw_env = args.get("env") or {}
    if not isinstance(raw_env, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in raw_env.items()
    ):
        return _tool_error_result("env 必须是 dict[str, str]")
    cwd = _coerce_str(args.get("cwd"))
    runner = get_runner()
    try:
        run = runner.start(script, args=list(raw_args), env=dict(raw_env), cwd=cwd)
    except FileNotFoundError as exc:
        return _tool_error_result(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _tool_error_result(f"启动子进程失败：{exc}")
    return _tool_text_result(
        {
            "run_id": run.id,
            "pid": run.pid,
            "started_at": run.started_at,
            "status": run.status,
        }
    )


def _resolve_run_or_error(args: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    run_id = _coerce_str(args.get("run_id"))
    if run_id is None:
        return None, _tool_error_result("run_id 必填")
    return run_id, None


def _call_status(args: dict[str, Any]) -> dict[str, Any]:
    run_id, err = _resolve_run_or_error(args)
    if err is not None:
        return err
    info = get_runner().status(run_id)
    if info is None:
        return _tool_error_result(f"未知 run_id：{run_id}")
    return _tool_text_result(info)


def _call_logs(args: dict[str, Any]) -> dict[str, Any]:
    run_id, err = _resolve_run_or_error(args)
    if err is not None:
        return err
    tail_raw = args.get("tail", 200)
    try:
        tail = int(tail_raw)
    except (TypeError, ValueError):
        return _tool_error_result("tail 须为整数")
    if tail < 1 or tail > 5000:
        return _tool_error_result("tail 须在 [1, 5000]")
    lines = get_runner().logs(run_id, tail=tail)
    if lines is None:
        return _tool_error_result(f"未知 run_id：{run_id}")
    return _tool_text_result({"run_id": run_id, "lines": lines})


def _call_metrics(args: dict[str, Any]) -> dict[str, Any]:
    run_id, err = _resolve_run_or_error(args)
    if err is not None:
        return err
    series = get_runner().metrics(run_id)
    if series is None:
        return _tool_error_result(f"未知 run_id：{run_id}")
    return _tool_text_result({"run_id": run_id, "metrics": series})


def _call_cancel(args: dict[str, Any]) -> dict[str, Any]:
    run_id, err = _resolve_run_or_error(args)
    if err is not None:
        return err
    ok = get_runner().cancel(run_id)
    if not ok:
        info = get_runner().status(run_id)
        if info is None:
            return _tool_error_result(f"未知 run_id：{run_id}")
        return _tool_text_result({"ok": False, "status": info["status"]})
    return _tool_text_result({"ok": True, "run_id": run_id})


_TOOL_DISPATCH = {
    "run_local": _call_run_local,
    "status": _call_status,
    "logs": _call_logs,
    "metrics": _call_metrics,
    "cancel": _call_cancel,
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
                response = _handle_tools_call(msg_id, params)
            else:
                response = _error(msg_id, -32601, f"method not supported: {method}")
        except Exception as exc:  # noqa: BLE001
            response = _error(msg_id, -32000, f"internal error: {exc}")

        await asyncio.to_thread(_write_message, stdout, response)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MambaResearch Experiment MCP server (stdio NDJSON JSON-RPC)",
    )
    parser.parse_args()
    asyncio.run(_main_loop())


# ---------------------------------------------------------------------------
# Claude Agent SDK 默认挂载配置
# ---------------------------------------------------------------------------

DEFAULT_SERVER_KEY = "mamba_experiment"


def default_mcp_config(root: Path) -> dict[str, dict[str, Any]]:
    if os.environ.get("MAMBA_EXPERIMENT_MCP_DISABLED", "").strip() == "1":
        return {}
    resolved_root = str(root.resolve())
    return {
        DEFAULT_SERVER_KEY: {
            "type": "stdio",
            "command": sys.executable,
            "args": [
                "-m",
                "src.server.integrations.experiment.mcp_server",
            ],
            "env": {"PYTHONPATH": resolved_root},
        },
    }


if __name__ == "__main__":
    main()
