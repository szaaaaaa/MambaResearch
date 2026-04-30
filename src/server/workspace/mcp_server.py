"""Workspace MCP server —— stdio newline-delimited JSON-RPC。

启动方式::

    python -m src.server.workspace.mcp_server

设计要点
~~~~~~~~
* **standalone**：只依赖 ``classification.py`` + ``scanner.py``——不引 dynamic_os
  也不依赖任何后端 web 进程，可被 Claude Code SDK 与 Codex CLI 任一启动
* **per-request 读 active project**：每次 ``tools/call`` 都重新读
  ``MAMBA_ACTIVE_PROJECT_PATH`` env var——这样用户在同一个 shell 里激活了
  不同 project 后，长生命 MCP 子进程会自动跟上；env 缺失就返 clean error，
  让前端能区分"环境问题"vs"工具失败"
* **NDJSON 协议**：每条消息一行 JSON、``\n`` 结尾，与 Claude Code SDK /
  Codex CLI 的 stdio MCP transport 一致；不要用 LSP 的 Content-Length 帧
  （那是 dynamic_os 内部 tool backend 协议）

工具暴露
~~~~~~~~
- ``scan``                  扫源目录，刷 sha256/mtime/size，新文件标 unknown
- ``classify_one``          Claude/Codex 看完文件后写分类
- ``list``                  按 bucket / subtype 列文件
- ``set_user_override``     用户手动校正（也可 LLM 代调）
- ``stats``                 概览
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.server.workspace.classification import (  # noqa: E402
    PRIMARY_BUCKETS,
    FileEntry,
    get_db_for_project,
)
from src.server.workspace.scanner import scan_source_dir  # noqa: E402


ACTIVE_PROJECT_ENV_VAR = "MAMBA_ACTIVE_PROJECT_PATH"
SERVER_NAME = "mamba-workspace"
SERVER_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# stdio NDJSON 帧
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
    """统一打包：``structuredContent`` + 文本镜像。

    Claude Code SDK 与 Codex CLI 都接受 ``content: [{type: text}]`` 形式；
    ``structuredContent`` 给客户端可解析对象（Claude SDK 会自动反序列化）。
    """
    text = json.dumps(structured, ensure_ascii=False)
    return {
        "structuredContent": structured,
        "content": [{"type": "text", "text": text}],
        "isError": False,
    }


def _tool_error_result(message: str) -> dict[str, Any]:
    """工具内部业务错误——走 ``isError: true`` 而非 JSON-RPC error。

    JSON-RPC error 是协议层失败（method 找不到、参数 schema 不合法）；业务
    异常（active project 缺失、path 不存在等）按 MCP 规范应返回 ``isError: true``
    给上层 LLM 自行决定如何应对。
    """
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


# ---------------------------------------------------------------------------
# Active project 解析
# ---------------------------------------------------------------------------


def _resolve_active_project() -> tuple[Path | None, str | None]:
    """读取并校验 ``MAMBA_ACTIVE_PROJECT_PATH``。

    Returns
    -------
    (path, error_message)
        ``path`` 解析成功；否则 ``error_message`` 是面向 LLM 的清晰提示。
    """
    raw = os.environ.get(ACTIVE_PROJECT_ENV_VAR, "").strip()
    if not raw:
        return None, (
            f"{ACTIVE_PROJECT_ENV_VAR} 未设置——无法定位 active project。"
            "请先在 MambaResearch 选/建一个 project。"
        )
    path = Path(raw)
    if not path.is_dir():
        return None, (
            f"{ACTIVE_PROJECT_ENV_VAR}={raw} 指向的目录不存在或不是目录。"
            "请重新激活 project 或检查路径。"
        )
    return path, None


# ---------------------------------------------------------------------------
# Tool descriptors（input_schema）
# ---------------------------------------------------------------------------


def _tool_descriptors() -> list[dict[str, Any]]:
    """返回 tools/list 给客户端看的工具元信息。"""
    bucket_enum = sorted(PRIMARY_BUCKETS)
    return [
        {
            "name": "scan",
            "description": (
                "扫描 active project 的 source_dirs（或指定 source_dir），"
                "把发现的新/改动文件入库为 primary_bucket=unknown。"
                "不读文件全文、不分类——分类需要后续调 classify_one。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source_dir": {
                        "type": "string",
                        "description": "可选；指定单个源目录。未给则扫所有已配置 source_dirs。",
                    }
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "classify_one",
            "description": (
                "把单个文件分类写入索引。respect_override=True——若该 path 已有 "
                "user_override=1 的记录则只刷新文件指纹不动分类字段。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件绝对路径"},
                    "primary_bucket": {
                        "type": "string",
                        "enum": bucket_enum,
                        "description": "experiment / literature / dataset / idea / unknown",
                    },
                    "subtype": {
                        "type": ["string", "null"],
                        "description": (
                            "类型细分：experiment 推荐 train_script / eval_script / "
                            "experiment_run_dir / config / metrics_log / checkpoint；"
                            "literature 推荐 paper_pdf / preprint / book / slides；"
                            "dataset 推荐 csv / parquet / npz / image_set / text_corpus；"
                            "idea 推荐 markdown_note / sketch / link_collection。"
                        ),
                    },
                    "summary": {
                        "type": ["string", "null"],
                        "description": "≤ 512 字摘要（文献请包含标题/作者）",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "自由 tag，便于跨 bucket 检索",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "分类置信度",
                    },
                    "classifier_model": {
                        "type": ["string", "null"],
                        "description": "执行分类的模型 ID，例如 claude-opus-4-7 / gpt-5.5",
                    },
                },
                "required": ["path", "primary_bucket"],
                "additionalProperties": False,
            },
        },
        {
            "name": "list",
            "description": "按 bucket / subtype 查询已分类文件，按 mtime 倒序。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "bucket": {
                        "type": ["string", "null"],
                        "enum": bucket_enum + [None],
                    },
                    "subtype": {"type": ["string", "null"]},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 2000,
                        "default": 50,
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "set_user_override",
            "description": (
                "标记一条用户校正——后续 LLM 分类不会再覆盖该行。"
                "适用场景：LLM 自分类错了 / 用户直接指定。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "primary_bucket": {
                        "type": "string",
                        "enum": bucket_enum,
                    },
                    "subtype": {"type": ["string", "null"]},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["path", "primary_bucket"],
                "additionalProperties": False,
            },
        },
        {
            "name": "stats",
            "description": (
                "返回索引概览：总数 / 各 bucket 计数 / 用户校正数 / 最近一次分类时间戳。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    ]


# ---------------------------------------------------------------------------
# Tool 调用分派
# ---------------------------------------------------------------------------


def _call_scan(arguments: dict[str, Any], project_path: Path) -> dict[str, Any]:
    db = get_db_for_project(project_path)
    src_raw = arguments.get("source_dir")
    sources: list[str]
    if isinstance(src_raw, str) and src_raw.strip():
        sources = [src_raw.strip()]
    else:
        # 没指定 → 读 workspace.json 拿全部 source_dirs。这里延迟 import 避免
        # 启动时拉 fastapi 依赖（projects.workspace 是纯 IO 模块，OK）
        from src.server.projects.workspace import load_workspace

        config = load_workspace(str(project_path))
        sources = list(config.source_dirs)
    if not sources:
        return _tool_error_result(
            "workspace 未配置 source_dirs；请在 MambaResearch 设置里添加源目录，"
            "或在调用时显式传 source_dir 参数。"
        )

    aggregate = {
        "scanned": 0,
        "new": 0,
        "changed": 0,
        "unchanged": 0,
        "skipped_large": 0,
        "skipped_dirs_count": 0,
        "truncated": False,
        "duration_s": 0.0,
        "per_source": [],
    }
    for src in sources:
        try:
            result = scan_source_dir(db, src)
        except ValueError as exc:
            return _tool_error_result(
                f"scan 失败：{exc}。在 Windows 上请用原生路径（例如 G:\\我的云端硬盘\\foo），"
                "MSYS / WSL 风格的 /g/... 不会被自动转换。"
            )
        d = result.to_dict()
        d["source_dir"] = src
        aggregate["per_source"].append(d)
        aggregate["scanned"] += d["scanned"]
        aggregate["new"] += d["new"]
        aggregate["changed"] += d["changed"]
        aggregate["unchanged"] += d["unchanged"]
        aggregate["skipped_large"] += d["skipped_large"]
        aggregate["skipped_dirs_count"] += d["skipped_dirs_count"]
        aggregate["truncated"] = aggregate["truncated"] or d["truncated"]
        aggregate["duration_s"] += d["duration_s"]
    aggregate["duration_s"] = round(aggregate["duration_s"], 2)
    return _tool_text_result(aggregate)


def _call_classify_one(
    arguments: dict[str, Any], project_path: Path
) -> dict[str, Any]:
    path = arguments.get("path")
    bucket = arguments.get("primary_bucket")
    if not isinstance(path, str) or not path.strip():
        return _tool_error_result("path 必填，须为文件绝对路径")
    if not isinstance(bucket, str) or bucket not in PRIMARY_BUCKETS:
        return _tool_error_result(
            f"primary_bucket 必填，且必须是 {sorted(PRIMARY_BUCKETS)} 之一"
        )

    db = get_db_for_project(project_path)
    existing = db.get_file(path.strip())
    if existing is None:
        # 文件未入库 → 提示先 scan，避免 LLM 凭空写入不存在的路径
        # 注：也可在这里现场 stat + sha 入库，但 scanner 已有那套逻辑，复用即可
        return _tool_error_result(
            f"文件未入索引：{path}。请先调 scan 工具扫源目录，"
            "或检查路径是否在已配置的 source_dirs 内。"
        )

    tags_raw = arguments.get("tags") or []
    if not isinstance(tags_raw, list) or any(not isinstance(t, str) for t in tags_raw):
        return _tool_error_result("tags 必须是字符串数组")

    confidence = float(arguments.get("confidence") or 0.0)
    if confidence < 0.0 or confidence > 1.0:
        return _tool_error_result("confidence 须在 [0.0, 1.0]")

    summary = arguments.get("summary")
    subtype = arguments.get("subtype")
    classifier_model = arguments.get("classifier_model")

    entry = FileEntry(
        path=path.strip(),
        sha256=existing.sha256,
        size=existing.size,
        mtime=existing.mtime,
        primary_bucket=bucket,
        subtype=subtype if isinstance(subtype, str) else None,
        summary=summary if isinstance(summary, str) else None,
        tags=list(tags_raw),
        confidence=confidence,
        user_override=False,
        classifier_model=(
            classifier_model if isinstance(classifier_model, str) else None
        ),
    )
    wrote = db.upsert_file(entry, respect_override=True)
    return _tool_text_result(
        {
            "path": entry.path,
            "primary_bucket": entry.primary_bucket,
            "subtype": entry.subtype,
            "wrote": wrote,
            "respected_override": not wrote,
        }
    )


def _call_list(arguments: dict[str, Any], project_path: Path) -> dict[str, Any]:
    bucket = arguments.get("bucket")
    if bucket is not None and (
        not isinstance(bucket, str) or bucket not in PRIMARY_BUCKETS
    ):
        return _tool_error_result(
            f"bucket 须为 {sorted(PRIMARY_BUCKETS)} 之一或 null"
        )
    subtype = arguments.get("subtype")
    if subtype is not None and not isinstance(subtype, str):
        return _tool_error_result("subtype 须为字符串或 null")
    limit_raw = arguments.get("limit", 50)
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        return _tool_error_result("limit 须为整数")
    if limit < 1 or limit > 2000:
        return _tool_error_result("limit 须在 [1, 2000]")

    db = get_db_for_project(project_path)
    rows = db.list_by_bucket(bucket, subtype=subtype, limit=limit)
    return _tool_text_result({"files": [r.to_dict() for r in rows]})


def _call_set_user_override(
    arguments: dict[str, Any], project_path: Path
) -> dict[str, Any]:
    path = arguments.get("path")
    bucket = arguments.get("primary_bucket")
    if not isinstance(path, str) or not path.strip():
        return _tool_error_result("path 必填")
    if not isinstance(bucket, str) or bucket not in PRIMARY_BUCKETS:
        return _tool_error_result(
            f"primary_bucket 须为 {sorted(PRIMARY_BUCKETS)} 之一"
        )
    subtype = arguments.get("subtype")
    if subtype is not None and not isinstance(subtype, str):
        return _tool_error_result("subtype 须为字符串或 null")
    tags_raw = arguments.get("tags") or []
    if not isinstance(tags_raw, list) or any(not isinstance(t, str) for t in tags_raw):
        return _tool_error_result("tags 必须是字符串数组")

    db = get_db_for_project(project_path)
    ok = db.set_user_override(
        path.strip(),
        bucket,
        subtype=subtype if isinstance(subtype, str) else None,
        tags=list(tags_raw),
    )
    if not ok:
        return _tool_error_result(
            f"文件未入索引：{path}。请先调 scan 让 scanner 入库。"
        )
    return _tool_text_result(
        {"path": path.strip(), "primary_bucket": bucket, "user_override": True}
    )


def _call_stats(_: dict[str, Any], project_path: Path) -> dict[str, Any]:
    db = get_db_for_project(project_path)
    return _tool_text_result(db.stats().to_dict())


_TOOL_DISPATCH = {
    "scan": _call_scan,
    "classify_one": _call_classify_one,
    "list": _call_list,
    "set_user_override": _call_set_user_override,
    "stats": _call_stats,
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

    project_path, err = _resolve_active_project()
    if project_path is None:
        return _result(msg_id, _tool_error_result(err or "active project 解析失败"))

    try:
        result = handler(arguments, project_path)
    except Exception as exc:  # noqa: BLE001
        # 业务异常（DB 损坏 / IO 错误等）——按工具错误返回，不抛 JSON-RPC 错
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
        description="MambaResearch workspace MCP server (stdio NDJSON JSON-RPC)",
    )
    parser.parse_args()
    asyncio.run(_main_loop())


# ---------------------------------------------------------------------------
# Claude Agent SDK 默认挂载配置
# ---------------------------------------------------------------------------

DEFAULT_SERVER_KEY = "mamba_workspace"


def default_mcp_config(root: Path) -> dict[str, dict[str, Any]]:
    """返回供 Claude Agent SDK ``mcp_servers`` 用的默认配置——挂本 server。

    返回 Claude Agent SDK ``mcp_servers`` 字段的标准形式（``type / command /
    args / env``）。session_manager 把多个 builtin helper 的 default config
    合并后传给 ``ClaudeAgentOptions``。

    设计要点
    --------
    * ``command = sys.executable``：保证 SDK spawn 子进程的 Python 与父后端一致
    * ``PYTHONPATH = repo root``：保证 ``-m src.server.workspace.mcp_server`` 能 import
    * **不在此处注入 ``MAMBA_ACTIVE_PROJECT_PATH``**：父后端进程的 env 已有该值
      （Stage 1 ``_apply_active_project_env``）；SDK 不带 ``env=`` 时子进程继承
      父 env，自然拿到最新值；session_manager 在 provider env 替换路径下显式
      propagate（已修复）。这样 active project 切换是"零中转"——不需要重启
      MCP server。
    * 允许通过 ``MAMBA_WORKSPACE_MCP_DISABLED=1`` 关闭（测试 / 故障兜底）

    Parameters
    ----------
    root : Path
        仓库根，用于 PYTHONPATH 与 ``-m`` 模块解析。
    """
    if os.environ.get("MAMBA_WORKSPACE_MCP_DISABLED", "").strip() == "1":
        return {}
    resolved_root = str(root.resolve())
    return {
        DEFAULT_SERVER_KEY: {
            "type": "stdio",
            "command": sys.executable,
            "args": [
                "-m",
                "src.server.workspace.mcp_server",
            ],
            "env": {"PYTHONPATH": resolved_root},
        },
    }


if __name__ == "__main__":
    main()
