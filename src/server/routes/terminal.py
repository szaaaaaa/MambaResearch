"""聊天面板的 PTY WebSocket 路由。

端点
----
``WS /api/terminal/{backend}``
    建立一条 PTY 通道。``backend`` 当前只支持 ``claude``（``codex`` 留待下个
    plan）。query params:

    * ``cwd`` —— 子进程工作目录；不传则用 active project 路径。必须存在。
    * ``provider`` —— provider registry 键（如 ``anthropic`` / ``deepseek``）；
      不传走 Anthropic 默认（继承父进程 env）。
    * ``resume`` —— 已有 session id（CLI 自带的本地 jsonl archive id），传则
      调 ``claude --resume <id>`` 接续历史。

WS 协议（与 spike 一致）
-----------------------
Client → Server:
    * binary frame：用户输入字节，整段 ``write_bytes`` 给 PTY stdin
    * text frame JSON：控制帧
        - ``{"type": "resize", "cols": N, "rows": M}``
        - ``{"type": "signal", "name": "SIGINT"}``

Server → Client:
    * text frame：PTY ``str`` 输出原文（含 ANSI），xterm 直接 ``write``
    * text frame JSON：fatal 错误 ``{"type": "fatal", "message": "..."}``
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.server.claude_code.providers import (
    ProviderRegistryError,
    get_provider_registry,
)
from src.server.projects import messages_store
from src.server.projects.registry import get_registry
from src.server.terminal.output_parser import TurnTeer
from src.server.terminal.pty_bridge import PtyBridge, build_subprocess_env

logger = logging.getLogger(__name__)

router = APIRouter()

SUPPORTED_BACKENDS = {"claude"}
NO_MIRROR_SENTINEL = "no-mirror"


def _resolve_argv(backend: str, *, resume: str | None) -> list[str]:
    """把 ``backend`` + 可选 ``resume`` 映射成 spawn argv。"""
    if backend == "claude":
        argv = ["claude"]
        if resume:
            argv.extend(["--resume", resume])
        return argv
    raise ValueError(f"unsupported backend: {backend!r}")


def _resolve_cwd(cwd_param: str | None) -> Path:
    """决定 PTY 子进程的 cwd——优先 query param，否则 active project path。"""
    if cwd_param:
        cwd = Path(cwd_param)
    else:
        active = get_registry().get_active()
        if active is None:
            raise ValueError("no cwd query param and no active project — pass ?cwd=...")
        cwd = Path(active.path)
    if not cwd.is_dir():
        raise ValueError(f"cwd does not exist or is not a directory: {cwd}")
    return cwd


def _should_mirror(conversation_id: str | None) -> bool:
    return bool(conversation_id and conversation_id != NO_MIRROR_SENTINEL)


async def _send_fatal(ws: WebSocket, message: str) -> None:
    payload = json.dumps({"type": "fatal", "message": message}, ensure_ascii=False)
    try:
        await ws.send_text(payload)
    except Exception:
        # WS 已断就吞掉
        pass


@router.websocket("/api/terminal/{backend}")
async def terminal_ws(websocket: WebSocket, backend: str) -> None:
    backend = backend.strip().lower()
    await websocket.accept()

    if backend not in SUPPORTED_BACKENDS:
        await _send_fatal(
            websocket,
            f"backend {backend!r} not supported in this plan; only {sorted(SUPPORTED_BACKENDS)}",
        )
        await websocket.close(code=1003)
        return

    cwd_param = websocket.query_params.get("cwd")
    provider_name = websocket.query_params.get("provider")
    resume_id = websocket.query_params.get("resume")
    conversation_id = websocket.query_params.get("conversation_id")

    try:
        cwd = _resolve_cwd(cwd_param)
    except ValueError as exc:
        await _send_fatal(websocket, str(exc))
        await websocket.close(code=1011)
        return

    provider = None
    if provider_name:
        registry = get_provider_registry()
        provider = registry.get(provider_name)
        if provider is None:
            await _send_fatal(
                websocket,
                f"provider {provider_name!r} not in registry "
                f"({sorted(registry.keys())})",
            )
            await websocket.close(code=1011)
            return

    try:
        env = build_subprocess_env(provider=provider)
    except ProviderRegistryError as exc:
        await _send_fatal(websocket, f"env build failed: {exc}")
        await websocket.close(code=1011)
        return

    try:
        argv = _resolve_argv(backend, resume=resume_id)
    except ValueError as exc:
        await _send_fatal(websocket, str(exc))
        await websocket.close(code=1011)
        return

    # PTY 模式下 claude CLI 通过 --mcp-config 加载 builtin MCP server
    # （SDK 模式删除后，这是 builtin MCP 唯一的子进程发现路径）。配置文件由
    # `_apply_active_project_env` → `write_builtin_mcp_config` 在 active
    # project 切换时整盘重写到 <project>/.mambaresearch/mcp_config.json；
    # 文件不存在（如未切 active / 写盘失败）则跳过 flag，PTY 仍可用但
    # 看不到 builtin MCP。
    if backend == "claude":
        from src.server.mcp.builtin_writer import builtin_mcp_config_path

        mcp_config = builtin_mcp_config_path(cwd)
        if mcp_config.exists():
            argv = [argv[0], "--mcp-config", str(mcp_config), *argv[1:]]

    logger.info(
        "spawning PTY backend=%s cwd=%s argv=%s provider=%s resume=%s conv=%s",
        backend,
        cwd,
        argv,
        provider_name or "<default>",
        resume_id or "<new>",
        conversation_id or "<no-mirror>",
    )

    # conversation_id 给定才挂 tee——没给说明前端不要这条 WS 写 messages 表
    # （比如纯设置面板里测试 PTY 时）。tee 抛异常不影响 PTY 主流（acceptance #4）。
    teer: TurnTeer | None = (
        TurnTeer(conversation_id, messages_store.append_message)
        if _should_mirror(conversation_id)
        else None
    )
    on_input = teer.on_user_input if teer else None
    on_output = teer.on_pty_output if teer else None

    try:
        async with PtyBridge(
            argv, cwd=cwd, env=env, on_input=on_input, on_output=on_output
        ) as pty:
            await _pump(websocket, pty)
    except Exception as exc:
        logger.exception("PTY session crashed")
        await _send_fatal(websocket, f"PTY crashed: {exc}")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        if teer is not None:
            teer.aclose()


async def _pump(websocket: WebSocket, pty: PtyBridge) -> None:
    """双向 pipe：PTY → WS 由 reader_task 跑；WS → PTY 在主循环里。"""

    async def reader_task() -> None:
        async for chunk in pty.read_chunks():
            try:
                await websocket.send_text(chunk)
            except Exception:
                # WS 已断——结束 reader，主循环也会收到 disconnect
                return

    reader = asyncio.create_task(reader_task())

    try:
        while True:
            receive = asyncio.create_task(websocket.receive())
            done, _pending = await asyncio.wait(
                {reader, receive}, return_when=asyncio.FIRST_COMPLETED
            )
            if reader in done:
                receive.cancel()
                with suppress(asyncio.CancelledError):
                    await receive
                try:
                    await websocket.close(code=1000)
                except Exception:
                    pass
                break

            msg = receive.result()
            msg_type = msg.get("type")
            if msg_type == "websocket.disconnect":
                break
            if msg_type != "websocket.receive":
                continue
            if msg.get("bytes") is not None:
                pty.write_bytes(msg["bytes"])
                continue
            text = msg.get("text")
            if text is None:
                continue
            try:
                ctrl = json.loads(text)
            except json.JSONDecodeError:
                # 文本帧但不是 JSON——按用户输入透传（极少见，但比静默丢更诚实）
                pty.write_str(text)
                continue
            await _handle_control(pty, ctrl, websocket)
    except WebSocketDisconnect:
        pass
    finally:
        reader.cancel()
        with suppress(asyncio.CancelledError):
            await reader


async def _handle_control(
    pty: PtyBridge, ctrl: dict[str, Any], websocket: WebSocket
) -> None:
    ctrl_type = ctrl.get("type")
    if ctrl_type == "resize":
        try:
            cols = int(ctrl.get("cols") or 0)
            rows = int(ctrl.get("rows") or 0)
        except (TypeError, ValueError):
            logger.warning("invalid resize frame: %s", ctrl)
            return
        if cols <= 0 or rows <= 0:
            logger.warning("resize frame ignored (cols/rows must be positive): %s", ctrl)
            return
        try:
            pty.resize(cols, rows)
        except Exception:
            logger.exception("pty.resize failed cols=%s rows=%s", cols, rows)
        return
    if ctrl_type == "signal" and ctrl.get("name") == "SIGINT":
        try:
            pty.signal_int()
        except Exception:
            logger.exception("pty.signal_int failed")
        return
    logger.warning("unknown control frame: %s", ctrl)
