from __future__ import annotations

import asyncio
import json
import traceback
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from src.common.config_utils import get_by_dotted, load_yaml, resolve_path
from src.common.openai_codex import ensure_openai_codex_auth
from src.dynamic_os.runtime import DynamicResearchRuntime
from src.server.settings import CONFIG_PATH, ROOT


router = APIRouter()
_ACTIVE_RUNS: dict[str, asyncio.Task[None]] = {}
_ACTIVE_RUNS_LOCK = asyncio.Lock()
_ACTIVE_RUNTIMES: dict[str, DynamicResearchRuntime] = {}
_ACTIVE_RUNTIMES_LOCK = asyncio.Lock()


def _normalize_provider(value: Any) -> str:
    provider = str(value or "").strip().lower()
    if provider in {"codex", "codex_cli", "chatgpt_codex", "openai_codex"}:
        return "openai_codex"
    if provider in {"google", "gemini"}:
        return "gemini"
    return provider


def _configured_llm_providers(config: dict[str, Any]) -> set[str]:
    providers: set[str] = set()
    for path in ("agent.routing.planner_llm.provider",):
        provider = _normalize_provider(get_by_dotted(config, path))
        if provider:
            providers.add(provider)

    role_models = get_by_dotted(config, "llm.role_models") or {}
    if isinstance(role_models, dict):
        for raw_entry in role_models.values():
            if not isinstance(raw_entry, dict):
                continue
            provider = _normalize_provider(raw_entry.get("provider"))
            if provider:
                providers.add(provider)
    return providers


def _preflight_run_config() -> list[str]:
    config = load_yaml(CONFIG_PATH) if CONFIG_PATH.exists() else {}
    issues: list[str] = []
    providers = _configured_llm_providers(config if isinstance(config, dict) else {})
    if "openai_codex" in providers:
        try:
            ensure_openai_codex_auth(config=config)
        except RuntimeError as exc:
            issues.append(str(exc))
    return issues


def _resolve_output_dir(payload: dict[str, Any]) -> Path:
    run_overrides = payload.get("runOverrides")
    if not isinstance(run_overrides, dict):
        return _get_outputs_dir()
    raw_path = str(run_overrides.get("output_dir", "") or "").strip() or "outputs"
    config = load_yaml(CONFIG_PATH) if CONFIG_PATH.exists() else {}
    return resolve_path(ROOT, raw_path, config if isinstance(config, dict) else {})


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


def _sse_frame(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


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
    preflight_issues = _preflight_run_config()
    if preflight_issues:
        raise HTTPException(status_code=400, detail=f"run preflight failed: {'; '.join(preflight_issues)}")
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    status_payload: dict[str, Any] = {
        "run_id": "",
        "status": "",
        "route_plan": {},
        "node_status": {},
        "artifacts": [],
        "report_text": "",
    }

    def emit_log(message: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        queue.put_nowait(_sse_frame("run_log", {"message": text}))

    def emit_event(payload_dict: dict[str, Any]) -> None:
        run_id = str(payload_dict.get("run_id") or "").strip()
        if run_id:
            status_payload["run_id"] = run_id
            if run_id not in _ACTIVE_RUNTIMES:
                _ACTIVE_RUNTIMES[run_id] = runtime
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
        queue.put_nowait(_sse_frame("run_event", payload_dict))
        emit_log(json.dumps(payload_dict, ensure_ascii=False))

    try:
        runtime = DynamicResearchRuntime(root=ROOT, output_root=output_dir, event_sink=emit_event)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def execute_run() -> None:
        try:
            result = await runtime.run(user_request=user_request)
        except asyncio.CancelledError:
            status_payload.update({"status": "stopped"})
            queue.put_nowait(_sse_frame("run_state", status_payload))
            raise
        except Exception as exc:
            status_payload.update({"status": "failed"})
            queue.put_nowait(_sse_frame("run_state", status_payload))
            emit_log(f"[dynamic_os run failed: {exc}]")
            emit_log(traceback.format_exc())
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
            queue.put_nowait(_sse_frame("run_state", status_payload))
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
            run_id_to_remove = status_payload.get("run_id", "")
            if run_id_to_remove:
                _ACTIVE_RUNTIMES.pop(run_id_to_remove, None)

    return StreamingResponse(
        generate_output(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def _get_outputs_dir() -> Path:
    config = load_yaml(CONFIG_PATH) if CONFIG_PATH.exists() else {}
    raw = get_by_dotted(config if isinstance(config, dict) else {}, "paths.outputs_dir")
    if raw:
        return resolve_path(ROOT, str(raw), config if isinstance(config, dict) else {})
    return (ROOT / "outputs").resolve()


def _run_timestamp(run_dir: Path) -> str:
    events_path = run_dir / "events.log"
    if events_path.exists():
        try:
            first_line = events_path.read_text(encoding="utf-8").splitlines()[0]
            return str(json.loads(first_line).get("ts") or "")
        except (json.JSONDecodeError, OSError, IndexError):
            pass
    return ""


def _run_topic(state: dict[str, Any]) -> str:
    report_text = str(state.get("report_text") or "").strip()
    for line in report_text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    route_plan = state.get("route_plan") or {}
    if not isinstance(route_plan, dict):
        return ""
    notes = route_plan.get("planner_notes")
    if isinstance(notes, list) and notes:
        first = str(notes[0] or "").strip()
        if first:
            return first
    nodes = route_plan.get("nodes")
    if isinstance(nodes, list) and nodes and isinstance(nodes[0], dict):
        goal = str(nodes[0].get("goal") or "").strip()
        if goal:
            return goal
    return ""


@router.get("/api/runs")
async def list_past_runs():
    outputs_dir = _get_outputs_dir()
    if not outputs_dir.exists():
        return []
    runs: list[dict[str, Any]] = []
    for run_dir in sorted(outputs_dir.iterdir(), reverse=True):
        if not run_dir.is_dir() or not run_dir.name.startswith("run_"):
            continue
        state_path = run_dir / "research_state.json"
        if not state_path.exists():
            continue
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        runs.append(
            {
                "run_id": str(state.get("run_id") or run_dir.name),
                "timestamp": _run_timestamp(run_dir),
                "topic": _run_topic(state),
                "status": str(state.get("status") or ""),
                "artifact_count": len(state.get("artifacts") or []),
            }
        )
    return runs


@router.get("/api/runs/{run_id}/state")
async def get_run_state(run_id: str):
    state_path = _get_outputs_dir() / run_id / "research_state.json"
    if not state_path.exists():
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"failed to read state: {exc}") from exc


@router.get("/api/runs/{run_id}/events")
async def get_run_events(run_id: str):
    events_path = _get_outputs_dir() / run_id / "events.log"
    if not events_path.exists():
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    events: list[dict[str, Any]] = []
    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to read events: {exc}") from exc
    return events


def _load_artifacts_full_from_disk(run_id: str) -> list[dict[str, Any]] | None:
    artifacts_path = _get_outputs_dir() / run_id / "artifacts_full.json"
    if not artifacts_path.exists():
        return None
    try:
        return json.loads(artifacts_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


@router.post("/api/runs/{run_id}/hitl")
async def submit_hitl_response(run_id: str, request: Request):
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="hitl payload must be an object")
    response_text = str(payload.get("response", "") or "").strip()
    if not response_text:
        raise HTTPException(status_code=400, detail="response is required")

    runtime = _ACTIVE_RUNTIMES.get(run_id)
    if runtime is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found or not active")

    try:
        runtime.submit_hitl_response(response_text)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"status": "accepted"}


@router.get("/api/runs/{run_id}/artifacts")
async def list_run_artifacts(run_id: str):
    runtime = _ACTIVE_RUNTIMES.get(run_id)
    if runtime is not None and runtime._artifact_store is not None:
        return [record.model_dump(mode="json") for record in runtime._artifact_store.list_all()]

    disk_records = _load_artifacts_full_from_disk(run_id)
    if disk_records is not None:
        return disk_records

    raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")


@router.get("/api/runs/{run_id}/artifacts/{artifact_id}")
async def get_run_artifact(run_id: str, artifact_id: str):
    runtime = _ACTIVE_RUNTIMES.get(run_id)
    if runtime is not None and runtime._artifact_store is not None:
        record = runtime._artifact_store.get(artifact_id)
        if record is not None:
            return record.model_dump(mode="json")
        raise HTTPException(status_code=404, detail=f"artifact {artifact_id!r} not found in active run {run_id!r}")

    disk_records = _load_artifacts_full_from_disk(run_id)
    if disk_records is not None:
        for record in disk_records:
            if record.get("artifact_id") == artifact_id:
                return record
        raise HTTPException(status_code=404, detail=f"artifact {artifact_id!r} not found in run {run_id!r}")

    raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")


@router.get("/api/runs/{run_id}/report.pdf")
async def get_run_report_pdf(run_id: str):
    run_dir = _get_outputs_dir() / run_id
    pdf_path = run_dir / "research_report.pdf"
    if not pdf_path.exists():
        tex_path = run_dir / "research_report.tex"
        if tex_path.exists():
            _ensure_bib_on_disk(run_dir)
            from src.dynamic_os.runtime import _compile_latex_report

            _compile_latex_report(tex_path.read_text(encoding="utf-8"), run_dir)
    if pdf_path.exists():
        return FileResponse(str(pdf_path), media_type="application/pdf", filename=f"{run_id}_report.pdf")
    raise HTTPException(status_code=404, detail=f"PDF report not found for run {run_id!r}")


@router.get("/api/runs/{run_id}/report.tex")
async def get_run_report_tex(run_id: str):
    tex_path = _get_outputs_dir() / run_id / "research_report.tex"
    if tex_path.exists():
        return FileResponse(str(tex_path), media_type="application/x-tex", filename=f"{run_id}_report.tex")
    raise HTTPException(status_code=404, detail=f"LaTeX source not found for run {run_id!r}")


@router.get("/api/runs/{run_id}/references.bib")
async def get_run_references_bib(run_id: str):
    run_dir = _get_outputs_dir() / run_id
    bib_path = run_dir / "references.bib"
    if not bib_path.exists():
        _ensure_bib_on_disk(run_dir)
    if bib_path.exists():
        return FileResponse(str(bib_path), media_type="application/x-bibtex", filename=f"references.bib")
    raise HTTPException(status_code=404, detail=f"BibTeX file not found for run {run_id!r}")


@router.get("/api/runs/{run_id}/latex.zip")
async def get_run_latex_zip(run_id: str):
    import io
    import zipfile

    run_dir = _get_outputs_dir() / run_id
    tex_path = run_dir / "research_report.tex"
    bib_path = run_dir / "references.bib"
    if not tex_path.exists():
        raise HTTPException(status_code=404, detail=f"LaTeX source not found for run {run_id!r}")
    if not bib_path.exists():
        _ensure_bib_on_disk(run_dir)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(str(tex_path), "research_report.tex")
        if bib_path.exists():
            zf.write(str(bib_path), "references.bib")
    buf.seek(0)
    from fastapi.responses import Response

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{run_id}_latex.zip"'},
    )


def _ensure_bib_on_disk(run_dir: Path) -> None:
    bib_path = run_dir / "references.bib"
    if bib_path.exists():
        return
    artifacts_path = run_dir / "artifacts_full.json"
    if not artifacts_path.exists():
        return
    from src.dynamic_os.contracts.artifact import ArtifactRecord
    from src.dynamic_os.runtime import _build_bib_from_artifacts

    records = [ArtifactRecord(**d) for d in json.loads(artifacts_path.read_text(encoding="utf-8"))]
    bib_content = _build_bib_from_artifacts(records)
    if bib_content.strip():
        bib_path.write_text(bib_content, encoding="utf-8")


@router.get("/api/knowledge-graph/status")
def get_knowledge_graph_status():
    config = load_yaml(CONFIG_PATH)
    kg_cfg = config.get("knowledge_graph") or {}
    persistence_mode = str(kg_cfg.get("persistence_mode", "memory")).strip()
    if persistence_mode != "sqlite":
        return {"enabled": False, "persistence_mode": "memory"}
    sqlite_path = str(kg_cfg.get("sqlite_path", "")).strip()
    if not sqlite_path:
        sqlite_path = str(ROOT / "data" / "knowledge_graph.db")
    resolved = resolve_path(ROOT, sqlite_path)
    if not Path(resolved).exists():
        return {"enabled": True, "persistence_mode": "sqlite", "node_count": 0, "edge_count": 0, "node_types": {}, "runs": []}
    from src.dynamic_os.storage.sqlite_store import init_knowledge_db
    from src.dynamic_os.storage.knowledge_graph import KnowledgeGraph
    conn = init_knowledge_db(str(resolved))
    kg = KnowledgeGraph(conn, run_id="__status_query__")
    summary = kg.summary_for_planner()
    runs_rows = conn.execute("SELECT id, topic, created_at, status FROM runs ORDER BY created_at DESC").fetchall()
    runs_list = [{"id": r["id"], "topic": r["topic"] or "", "created_at": r["created_at"] or ""} for r in runs_rows]
    kg.close()
    conn.close()
    return {
        "enabled": True,
        "persistence_mode": "sqlite",
        "node_count": summary["node_count"],
        "edge_count": summary["edge_count"],
        "node_types": summary["node_types"],
        "run_ids": summary["run_ids"],
        "runs": runs_list,
    }


@router.get("/api/knowledge-graph/nodes")
def list_knowledge_graph_nodes(node_type: str | None = None, run_id: str | None = None):
    config = load_yaml(CONFIG_PATH)
    kg_cfg = config.get("knowledge_graph") or {}
    persistence_mode = str(kg_cfg.get("persistence_mode", "memory")).strip()
    if persistence_mode != "sqlite":
        return []
    sqlite_path = str(kg_cfg.get("sqlite_path", "")).strip()
    if not sqlite_path:
        sqlite_path = str(ROOT / "data" / "knowledge_graph.db")
    resolved = resolve_path(ROOT, sqlite_path)
    if not Path(resolved).exists():
        return []
    from src.dynamic_os.storage.sqlite_store import init_knowledge_db
    from src.dynamic_os.storage.knowledge_graph import KnowledgeGraph
    conn = init_knowledge_db(str(resolved))
    kg = KnowledgeGraph(conn, run_id="__query__")
    if node_type:
        results = kg.search_by_type(node_type)
    else:
        results = [{"id": n, **data} for n, data in kg._graph.nodes(data=True)]
    if run_id:
        results = [r for r in results if r.get("run_id") == run_id]
    kg.close()
    conn.close()
    return results[:500]
