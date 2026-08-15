"""聊天面板的 PTY WebSocket 路由。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.server.kernel.contracts import (
    BackendLaunchError,
    LaunchRequest,
    UnknownCapabilityError,
)
from src.server.projects import messages_store
from src.server.projects.conversations import add_segment, get_conversation
from src.server.projects.registry import get_registry
from src.server.terminal.output_parser import TurnTeer
from src.server.terminal.pty_bridge import PtyBridge

logger = logging.getLogger(__name__)

router = APIRouter()

NO_MIRROR_SENTINEL = "no-mirror"


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


async def _send_fatal(websocket: WebSocket, message: str) -> None:
    payload = json.dumps({"type": "fatal", "message": message}, ensure_ascii=False)
    try:
        await websocket.send_text(payload)
    except Exception:
        pass


@router.websocket("/api/terminal/{backend_id}")
async def terminal_ws(websocket: WebSocket, backend_id: str) -> None:
    backend_id = backend_id.strip().lower()
    await websocket.accept()

    try:
        backend = websocket.app.state.kernel.context.capabilities.backends.require(backend_id)
    except UnknownCapabilityError as exc:
        await _send_fatal(websocket, str(exc))
        await websocket.close(code=1003)
        return

    cwd_param = websocket.query_params.get("cwd")
    provider_id = websocket.query_params.get("provider")
    resume_id = websocket.query_params.get("resume")
    conversation_id = websocket.query_params.get("conversation_id")

    if _should_mirror(conversation_id):
        conversation = get_conversation(conversation_id)
        if conversation is None or conversation.backend != backend_id:
            await _send_fatal(
                websocket,
                f"conversation {conversation_id!r} does not belong to backend {backend_id!r}",
            )
            await websocket.close(code=1003)
            return

    try:
        cwd = _resolve_cwd(cwd_param)
    except ValueError as exc:
        await _send_fatal(websocket, str(exc))
        await websocket.close(code=1011)
        return

    try:
        spec = backend.resolve_launch(
            LaunchRequest(
                cwd=cwd,
                resume_id=resume_id,
                provider_id=provider_id,
            )
        )
    except BackendLaunchError as exc:
        await _send_fatal(websocket, str(exc))
        await websocket.close(code=1011)
        return

    logger.info(
        "spawning PTY backend=%s cwd=%s argv=%s provider=%s resume=%s conv=%s",
        backend_id,
        spec.cwd,
        spec.argv,
        provider_id or "<default>",
        resume_id or "<new>",
        conversation_id or "<no-mirror>",
    )

    teer: TurnTeer | None = (
        TurnTeer(
            conversation_id,
            messages_store.append_message,
            assistant_served_by=backend_id,
        )
        if _should_mirror(conversation_id)
        else None
    )
    on_input = teer.on_user_input if teer else None
    on_output = teer.on_pty_output if teer else None
    session_task: asyncio.Task[None] | None = None

    try:
        async with PtyBridge(
            spec.argv,
            cwd=spec.cwd,
            env=spec.env,
            on_input=on_input,
            on_output=on_output,
        ) as pty:
            if teer is not None and spec.session_id_resolver is not None:
                session_task = asyncio.create_task(
                    _register_session(
                        conversation_id=conversation_id,
                        backend_id=backend_id,
                        resolver=spec.session_id_resolver,
                    )
                )
            await _pump(websocket, pty)
    except Exception as exc:
        logger.exception("PTY session crashed")
        await _send_fatal(websocket, f"PTY crashed: {exc}")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        if session_task is not None:
            await session_task
        if teer is not None:
            teer.aclose()


async def _register_session(
    *,
    conversation_id: str,
    backend_id: str,
    resolver: Callable[[], str | None],
) -> None:
    session_id = await asyncio.to_thread(resolver)
    if session_id is None:
        logger.warning("backend=%s session ID was not discovered", backend_id)
        return
    conversation = get_conversation(conversation_id)
    if conversation is None or conversation.backend != backend_id:
        return
    add_segment(
        conversation_id=conversation_id,
        backend=backend_id,
        cli_session_id=session_id,
    )


async def _pump(websocket: WebSocket, pty: PtyBridge) -> None:
    """双向 pipe：PTY → WS 由 reader_task 跑；WS → PTY 在主循环里。"""

    async def reader_task() -> None:
        async for chunk in pty.read_chunks():
            try:
                await websocket.send_text(chunk)
            except Exception:
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

            message = receive.result()
            message_type = message.get("type")
            if message_type == "websocket.disconnect":
                break
            if message_type != "websocket.receive":
                continue
            if message.get("bytes") is not None:
                pty.write_bytes(message["bytes"])
                continue
            text = message.get("text")
            if text is None:
                continue
            try:
                control = json.loads(text)
            except json.JSONDecodeError:
                pty.write_str(text)
                continue
            await _handle_control(pty, control, websocket)
    except WebSocketDisconnect:
        pass
    finally:
        reader.cancel()
        with suppress(asyncio.CancelledError):
            await reader


async def _handle_control(
    pty: PtyBridge, control: dict[str, Any], websocket: WebSocket
) -> None:
    control_type = control.get("type")
    if control_type == "resize":
        try:
            cols = int(control.get("cols") or 0)
            rows = int(control.get("rows") or 0)
        except (TypeError, ValueError):
            logger.warning("invalid resize frame: %s", control)
            return
        if cols <= 0 or rows <= 0:
            logger.warning("resize frame ignored (cols/rows must be positive): %s", control)
            return
        try:
            pty.resize(cols, rows)
        except Exception:
            logger.exception("pty.resize failed cols=%s rows=%s", cols, rows)
        return
    if control_type == "signal" and control.get("name") == "SIGINT":
        try:
            pty.signal_int()
        except Exception:
            logger.exception("pty.signal_int failed")
        return
    logger.warning("unknown control frame: %s", control)
