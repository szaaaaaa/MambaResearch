"""Zotero MCP server —— stdio newline-delimited JSON-RPC。

启动方式::

    python -m src.server.integrations.zotero.mcp_server

设计要点
~~~~~~~~
* **standalone**：只依赖 ``client.py`` + ``credentials.py``——不引 web 进程，
  可被 Claude Code SDK 与 Codex CLI 任一启动
* **lazy ZoteroClient**：每次 ``tools/call`` 现场构造 client；这样用户在 .env
  里改了 ``ZOTERO_USER_ID`` / ``ZOTERO_API_KEY`` 后无需重启 MCP server
* **凭据缺失走 ``isError: true``**：与 workspace MCP 同语义——业务层错误不抛
  JSON-RPC error，而是把面向用户的引导扁平回传给 LLM 自己处置
* **NDJSON 协议**：与 ``src/server/workspace/mcp_server.py`` 同形

工具暴露
~~~~~~~~
- ``search``           全文搜 user library
- ``list_collections`` 列 collection
- ``get_item``         单 item 详情
- ``add_tag``          追加 tag
- ``upload_pdf``       上传本地 PDF（创建 attachment item + 文件）
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

from src.server.integrations.zotero.client import ZoteroClient  # noqa: E402
from src.server.integrations.zotero.credentials import (  # noqa: E402
    ZoteroCredentialsMissing,
    load_zotero_credentials,
)


SERVER_NAME = "mamba-zotero"
SERVER_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# stdio NDJSON 帧（与 workspace mcp_server 同形）
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
# Lazy client 工厂（每个 tools/call 调一次）
# ---------------------------------------------------------------------------


# 类层级注入点，便于测试 mock：把 ``_client_factory`` 替换为 lambda 返回 fake。
_client_factory = ZoteroClient


def _make_client() -> tuple[Any | None, str | None]:
    """构造一个 ZoteroClient；缺凭据返回 (None, guidance_message)。"""
    try:
        creds = load_zotero_credentials()
    except ZoteroCredentialsMissing as exc:
        return None, str(exc)
    try:
        return _client_factory(credentials=creds), None
    except Exception as exc:  # noqa: BLE001
        return None, f"无法初始化 Zotero client：{exc}"


# ---------------------------------------------------------------------------
# Tool descriptors
# ---------------------------------------------------------------------------


def _tool_descriptors() -> list[dict[str, Any]]:
    return [
        {
            "name": "search",
            "description": "全文搜 Zotero user library，返回匹配的 item 列表（key/title/itemType/creators）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "自由文本查询"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 20,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "list_collections",
            "description": "列出当前 user library 的所有 collection（key + name）。",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "get_item",
            "description": "取单个 item 的详情（data 段，含 title / creators / tags / version 等）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string", "description": "Zotero item key（8 位字母数字）"},
                },
                "required": ["item_key"],
                "additionalProperties": False,
            },
        },
        {
            "name": "add_tag",
            "description": "给 item 追加 tag（与现有 tag 合并，不覆盖）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                },
                "required": ["item_key", "tags"],
                "additionalProperties": False,
            },
        },
        {
            "name": "upload_pdf",
            "description": (
                "上传本地 PDF 到 Zotero user library，可选指定 collection / tags / title / authors。"
                "成功返回 item_key；服务端已存在同 md5 文件时跳过实际上传但仍创建 item 记录。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "local_path": {
                        "type": "string",
                        "description": "本地 PDF 绝对路径；扩展名必须是 .pdf",
                    },
                    "collection": {
                        "type": ["string", "null"],
                        "description": "目标 collection key；不传则放 unfiled",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "title": {
                        "type": ["string", "null"],
                        "description": "不传则用文件名（去扩展名）",
                    },
                    "authors": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["local_path"],
                "additionalProperties": False,
            },
        },
    ]


# ---------------------------------------------------------------------------
# Tool 调用分派
# ---------------------------------------------------------------------------


def _coerce_str(value: Any, *, allow_empty: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not allow_empty and not stripped:
        return None
    return stripped


def _coerce_str_list(value: Any) -> list[str] | None:
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        s = item.strip()
        if s:
            out.append(s)
    return out


def _call_search(arguments: dict[str, Any], client: Any) -> dict[str, Any]:
    query = _coerce_str(arguments.get("query"))
    if query is None:
        return _tool_error_result("query 必填，须为非空字符串")
    limit_raw = arguments.get("limit", 20)
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        return _tool_error_result("limit 须为整数")
    if limit < 1 or limit > 100:
        return _tool_error_result("limit 须在 [1, 100]")
    try:
        items = client.search(query, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return _tool_error_result(f"Zotero 搜索失败：{exc}")
    return _tool_text_result({"query": query, "items": items})


def _call_list_collections(_: dict[str, Any], client: Any) -> dict[str, Any]:
    try:
        items = client.list_collections()
    except Exception as exc:  # noqa: BLE001
        return _tool_error_result(f"列 collection 失败：{exc}")
    return _tool_text_result({"collections": items})


def _call_get_item(arguments: dict[str, Any], client: Any) -> dict[str, Any]:
    key = _coerce_str(arguments.get("item_key"))
    if key is None:
        return _tool_error_result("item_key 必填")
    try:
        data = client.get_item(key)
    except Exception as exc:  # noqa: BLE001
        return _tool_error_result(f"取 item 失败：{exc}")
    return _tool_text_result({"item_key": key, "data": data})


def _call_add_tag(arguments: dict[str, Any], client: Any) -> dict[str, Any]:
    key = _coerce_str(arguments.get("item_key"))
    if key is None:
        return _tool_error_result("item_key 必填")
    tags = _coerce_str_list(arguments.get("tags"))
    if tags is None:
        return _tool_error_result("tags 必须是字符串数组")
    if not tags:
        return _tool_error_result("tags 至少含一个非空字符串")
    try:
        result = client.add_tag(key, tags)
    except Exception as exc:  # noqa: BLE001
        return _tool_error_result(f"加 tag 失败：{exc}")
    if not result.get("ok"):
        return _tool_error_result(f"加 tag 失败：{result.get('error', 'unknown')}")
    return _tool_text_result({"item_key": key, "tags": result.get("tags", [])})


def _call_upload_pdf(arguments: dict[str, Any], client: Any) -> dict[str, Any]:
    path = _coerce_str(arguments.get("local_path"))
    if path is None:
        return _tool_error_result("local_path 必填")
    collection = _coerce_str(arguments.get("collection"), allow_empty=False)
    title = _coerce_str(arguments.get("title"), allow_empty=False)
    tags = _coerce_str_list(arguments.get("tags"))
    if tags is None:
        return _tool_error_result("tags 必须是字符串数组")
    authors = _coerce_str_list(arguments.get("authors"))
    if authors is None:
        return _tool_error_result("authors 必须是字符串数组")
    try:
        result = client.upload_pdf(
            local_path=path,
            collection=collection,
            tags=tags,
            title=title,
            authors=authors,
        )
    except Exception as exc:  # noqa: BLE001
        return _tool_error_result(f"上传 PDF 失败：{exc}")
    if not result.get("ok"):
        return _tool_error_result(f"上传 PDF 失败：{result.get('error', 'unknown')}")
    return _tool_text_result(result)


_TOOL_DISPATCH = {
    "search": _call_search,
    "list_collections": _call_list_collections,
    "get_item": _call_get_item,
    "add_tag": _call_add_tag,
    "upload_pdf": _call_upload_pdf,
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

    client, err = _make_client()
    if client is None:
        return _result(msg_id, _tool_error_result(err or "Zotero client 初始化失败"))

    try:
        result = handler(arguments, client)
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
        description="MambaResearch Zotero MCP server (stdio NDJSON JSON-RPC)",
    )
    parser.parse_args()
    asyncio.run(_main_loop())


# ---------------------------------------------------------------------------
# Claude Agent SDK 默认挂载配置（供 session_manager 合并使用）
# ---------------------------------------------------------------------------

DEFAULT_SERVER_KEY = "mamba_zotero"


def default_mcp_config(root: Path) -> dict[str, dict[str, Any]]:
    """返回供 Claude Agent SDK ``mcp_servers`` 用的默认配置。

    与 ``src/server/workspace/mcp_server.py:default_mcp_config`` 同形。
    凭据走子进程继承 ``ZOTERO_*`` env，不在此处显式注入；用户改 .env 后
    重启后端即可，无需重启 MCP 子进程（client 会每次重新读 env）。

    通过 ``MAMBA_ZOTERO_MCP_DISABLED=1`` 关闭。
    """
    if os.environ.get("MAMBA_ZOTERO_MCP_DISABLED", "").strip() == "1":
        return {}
    resolved_root = str(root.resolve())
    return {
        DEFAULT_SERVER_KEY: {
            "type": "stdio",
            "command": sys.executable,
            "args": [
                "-m",
                "src.server.integrations.zotero.mcp_server",
            ],
            "env": {"PYTHONPATH": resolved_root},
        },
    }


if __name__ == "__main__":
    main()
