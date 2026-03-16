#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.config_utils import load_yaml
from src.dynamic_os.tools.backends import ConfiguredToolBackend
from src.server.routes.config import _read_env_file
from src.server.settings import CONFIG_PATH


def _read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in {b"\n", b"\r\n"}:
            break
        key, _, value = line.decode("utf-8").partition(":")
        headers[key.strip().lower()] = value.strip()
    content_length = int(headers.get("content-length") or 0)
    if content_length <= 0:
        return None
    body = sys.stdin.buffer.read(content_length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write_message(payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def _result_response(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error_response(message_id: Any, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": -32000, "message": message}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Dynamic OS MCP server")
    parser.add_argument("--server-id", required=True)
    parser.add_argument("--root", type=str, default=str(ROOT))
    args = parser.parse_args()

    backend = ConfiguredToolBackend(
        root=Path(args.root).resolve(),
        config=load_yaml(CONFIG_PATH),
        saved_env=_read_env_file(),
    )
    server_id = str(args.server_id).strip()

    while True:
        message = _read_message()
        if message is None:
            return
        message_id = message.get("id")
        method = str(message.get("method") or "").strip()
        params = dict(message.get("params") or {})

        try:
            if method == "initialize":
                response = _result_response(
                    message_id,
                    {
                        "serverInfo": {
                            "name": f"dynamic-os-{server_id}",
                            "version": "1.0.0",
                        }
                    },
                )
            elif method == "tools/list":
                response = _result_response(
                    message_id,
                    {
                        "tools": backend.list_server_tools(server_id),
                    },
                )
            elif method == "tools/call":
                tool_name = str(params.get("name") or "").strip()
                arguments = dict(params.get("arguments") or {})
                content, usage = backend.invoke(server_id, tool_name, arguments)
                response = _result_response(
                    message_id,
                    {
                        "structuredContent": content,
                        "content": [
                            {
                                "type": "text",
                                "text": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                            }
                        ],
                        "usage": usage,
                        "isError": False,
                    },
                )
            else:
                response = _error_response(message_id, f"unsupported method: {method}")
        except Exception as exc:
            response = _error_response(message_id, str(exc))

        _write_message(response)


if __name__ == "__main__":
    main()
