from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.dynamic_os.runtime import DynamicResearchRuntime
from src.server.settings import ROOT, RUN_EVENT_PREFIX, RUN_LOG_PREFIX, RUN_STATE_PREFIX


router = APIRouter()
_ACTIVE_RUNS: dict[str, asyncio.Task[None]] = {}
_ACTIVE_RUNS_LOCK = asyncio.Lock()


def _resolve_output_dir(payload: dict[str, Any]) -> Path:
    run_overrides = payload.get("runOverrides")
    if not isinstance(run_overrides, dict):
        return (ROOT / "outputs").resolve()
    raw_path = str(run_overrides.get("output_dir", "") or "").strip() or "outputs"
    output_dir = Path(raw_path)
    if not output_dir.is_absolute():
        output_dir = (ROOT / output_dir).resolve()
    return output_dir


def _resolve_user_request(payload: dict[str, Any]) -> str:
    run_overrides = payload.get("runOverrides")
    if not isinstance(run_overrides, dict):
        raise HTTPException(status_code=400, detail="runOverrides is required")
    user_request = str(run_overrides.get("user_request", "") or "").strip()
    topic = str(run_overrides.get("topic", "") or "").strip()
    resume_run_id = str(run_overrides.get("resume_run_id", "") or "").strip()
    if resume_run_id:
        raise HTTPException(status_code=400, detail="resume_run_id is not supported on the dynamic_os runtime")
    resolved_request = user_request or topic
    if not resolved_request:
        raise HTTPException(status_code=400, detail="topic or user_request is required")
    return resolved_request


async def _register_active_run(client_request_id: str, task: asyncio.Task[None]) -> None:
    async with _ACTIVE_RUNS_LOCK:
        _ACTIVE_RUNS[client_request_id] = task


async def _unregister_active_run(client_request_id: str, task: asyncio.Task[None] | None = None) -> None:
    async with _ACTIVE_RUNS_LOCK:
        current = _ACTIVE_RUNS.get(client_request_id)
        if task is not None and current is not task:
            return
        _ACTIVE_RUNS.pop(client_request_id, None)


@router.post("/api/run/stop")
async def stop_run(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="stop payload must be an object")
    client_request_id = str(payload.get("client_request_id", "")).strip()
    if not client_request_id:
        raise HTTPException(status_code=400, detail="client_request_id is required")

    async with _ACTIVE_RUNS_LOCK:
        task = _ACTIVE_RUNS.get(client_request_id)

    if task is None:
        return {"status": "not_found"}
    if task.done():
        await _unregister_active_run(client_request_id, task)
        return {"status": "already_exited"}

    task.cancel()
    return {"status": "terminated"}


@router.post("/api/run")
async def run_agent(request: Request):
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="run payload must be an object")

    client_request_id = str(payload.get("client_request_id", "")).strip()
    if not client_request_id:
        raise HTTPException(status_code=400, detail="client_request_id is required")

    user_request = _resolve_user_request(payload)
    output_dir = _resolve_output_dir(payload)
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    status_payload: dict[str, Any] = {
        "run_id": "",
        "status": "",
        "route_plan": {},
        "node_status": {},
        "artifacts": [],
        "report_text": "",
    }

    def emit_event(payload_dict: dict[str, Any]) -> None:
        run_id = str(payload_dict.get("run_id") or "").strip()
        if run_id:
            status_payload["run_id"] = run_id
        if payload_dict.get("type") == "plan_update" and isinstance(payload_dict.get("plan"), dict):
            status_payload["route_plan"] = payload_dict["plan"]
        if payload_dict.get("type") == "node_status" and payload_dict.get("node_id"):
            status_payload["node_status"][str(payload_dict["node_id"])] = str(payload_dict.get("status") or "")
        if payload_dict.get("type") == "artifact_created":
            status_payload["artifacts"].append(
                {
                    "artifact_id": str(payload_dict.get("artifact_id") or ""),
                    "artifact_type": str(payload_dict.get("artifact_type") or ""),
                    "producer_role": str(payload_dict.get("producer_role") or ""),
                    "producer_skill": str(payload_dict.get("producer_skill") or ""),
                }
            )
        queue.put_nowait(f"{RUN_EVENT_PREFIX}{json.dumps(payload_dict, ensure_ascii=False)}\n")

    try:
        runtime = DynamicResearchRuntime(root=ROOT, output_root=output_dir, event_sink=emit_event)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def execute_run() -> None:
        try:
            result = await runtime.run(user_request=user_request)
        except asyncio.CancelledError:
            status_payload.update({"status": "stopped"})
            queue.put_nowait(f"{RUN_STATE_PREFIX}{json.dumps(status_payload, ensure_ascii=False)}\n")
            queue.put_nowait(f"{RUN_LOG_PREFIX}[dynamic_os run stopped]\n")
            raise
        except Exception as exc:
            status_payload.update({"status": "failed"})
            queue.put_nowait(f"{RUN_STATE_PREFIX}{json.dumps(status_payload, ensure_ascii=False)}\n")
            queue.put_nowait(f"{RUN_LOG_PREFIX}[dynamic_os run failed: {exc}]\n")
        else:
            status_payload.update(
                {
                    "run_id": result.run_id,
                    "status": result.status,
                    "route_plan": result.route_plan,
                    "node_status": result.node_status,
                    "artifacts": result.artifacts,
                    "report_text": result.report_text,
                }
            )
            queue.put_nowait(f"{RUN_STATE_PREFIX}{json.dumps(status_payload, ensure_ascii=False)}\n")
            if result.report_text.strip():
                queue.put_nowait(result.report_text)
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(execute_run())
    await _register_active_run(client_request_id, task)

    async def generate_output():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            else:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await _unregister_active_run(client_request_id, task)

    return StreamingResponse(generate_output(), media_type="text/plain")
