"""Colab MCP server —— stdio NDJSON。

工具
~~~~
- ``url_for(local_path)``  本地 .ipynb → ``{colab_url, mode, drive_id?}``
- ``url_for_github(repo, path, branch?)``  github → colab URL（无需 Drive）

模式 (``mode`` 字段)：
- ``drive_id``：成功反查 Drive ID，URL 形如 ``colab.research.google.com/drive/<id>``
- ``fallback``：路径在本地但 Drive ID 反查失败（DriveFS 没装 / SQLite 不可读 /
  文件未同步），URL = ``colab.research.google.com/drive/upload``，需用户手动上传
- ``github``：URL = ``colab.research.google.com/github/<repo>/blob/<branch>/<path>``
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

from src.server.integrations.colab.drive_locator import resolve_drive_id  # noqa: E402


SERVER_NAME = "mamba-colab"
SERVER_VERSION = "1.0.0"
COLAB_BASE = "https://colab.research.google.com"
FALLBACK_UPLOAD_URL = f"{COLAB_BASE}/drive/upload"


# ---------------------------------------------------------------------------
# stdio NDJSON 帧（与其他 MCP server 同形）
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
            "name": "url_for",
            "description": (
                "本地 .ipynb 路径 → Colab URL。"
                "首选 Drive Desktop 元数据反查 drive_id；失败回退到 fallback "
                "上传 URL（colab.research.google.com/drive/upload）让用户手动上传。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "local_path": {
                        "type": "string",
                        "description": "本地 .ipynb 绝对路径",
                    },
                },
                "required": ["local_path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "url_for_github",
            "description": (
                "GitHub 路径直接拼 Colab URL（无需 Drive 同步）。"
                "形如 colab.research.google.com/github/<repo>/blob/<branch>/<path>。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "形如 'owner/name'",
                    },
                    "path": {
                        "type": "string",
                        "description": "仓库内 .ipynb 相对路径",
                    },
                    "branch": {
                        "type": "string",
                        "default": "main",
                    },
                },
                "required": ["repo", "path"],
                "additionalProperties": False,
            },
        },
    ]


# ---------------------------------------------------------------------------
# Tool 调用
# ---------------------------------------------------------------------------


def _call_url_for(arguments: dict[str, Any]) -> dict[str, Any]:
    raw = arguments.get("local_path")
    if not isinstance(raw, str) or not raw.strip():
        return _tool_error_result("local_path 必填")
    path = Path(raw.strip())
    if path.suffix.lower() != ".ipynb":
        return _tool_error_result(
            f"local_path 必须以 .ipynb 结尾，got {path.suffix or '<no ext>'}"
        )
    if not path.exists():
        return _tool_error_result(f"文件不存在：{path}")

    drive_id = resolve_drive_id(path)
    if drive_id:
        return _tool_text_result(
            {
                "colab_url": f"{COLAB_BASE}/drive/{drive_id}",
                "mode": "drive_id",
                "drive_id": drive_id,
                "local_path": str(path),
            }
        )
    return _tool_text_result(
        {
            "colab_url": FALLBACK_UPLOAD_URL,
            "mode": "fallback",
            "drive_id": None,
            "local_path": str(path),
            "hint": (
                "未在 Drive Desktop 元数据中找到该文件——可能是：(a) Drive Desktop "
                "未安装；(b) 文件不在 Drive 同步目录；(c) 文件未完成同步。"
                "fallback URL 让你手动上传到 Colab。"
            ),
        }
    )


def _call_url_for_github(arguments: dict[str, Any]) -> dict[str, Any]:
    repo = arguments.get("repo")
    path = arguments.get("path")
    branch_raw = arguments.get("branch", "main")
    if not isinstance(repo, str) or "/" not in repo or not repo.strip("/"):
        return _tool_error_result("repo 必填，且须为 'owner/name' 形式")
    if not isinstance(path, str) or not path.strip():
        return _tool_error_result("path 必填，须为仓库内 .ipynb 相对路径")
    branch = branch_raw if isinstance(branch_raw, str) and branch_raw.strip() else "main"
    repo_clean = repo.strip().strip("/")
    path_clean = path.strip().lstrip("/")
    return _tool_text_result(
        {
            "colab_url": f"{COLAB_BASE}/github/{repo_clean}/blob/{branch.strip()}/{path_clean}",
            "mode": "github",
            "repo": repo_clean,
            "path": path_clean,
            "branch": branch.strip(),
        }
    )


_TOOL_DISPATCH = {
    "url_for": _call_url_for,
    "url_for_github": _call_url_for_github,
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
        description="MambaResearch Colab MCP server (stdio NDJSON JSON-RPC)",
    )
    parser.parse_args()
    asyncio.run(_main_loop())


# ---------------------------------------------------------------------------
# Claude Agent SDK 默认挂载配置
# ---------------------------------------------------------------------------

DEFAULT_SERVER_KEY = "mamba_colab"


def default_mcp_config(root: Path) -> dict[str, dict[str, Any]]:
    """与 zotero / workspace 同形。``MAMBA_COLAB_MCP_DISABLED=1`` 关闭。"""
    if os.environ.get("MAMBA_COLAB_MCP_DISABLED", "").strip() == "1":
        return {}
    resolved_root = str(root.resolve())
    return {
        DEFAULT_SERVER_KEY: {
            "type": "stdio",
            "command": sys.executable,
            "args": [
                "-m",
                "src.server.integrations.colab.mcp_server",
            ],
            "env": {"PYTHONPATH": resolved_root},
        },
    }


if __name__ == "__main__":
    main()
