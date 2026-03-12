import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.server.routes.config import _merge_runtime_credentials, _read_env_file
from src.server.settings import (
    ACTIVE_RUNS_PATH,
    ROOT,
    RUN_EVENT_PREFIX,
    RUN_LOG_PREFIX,
    RUN_STATE_PREFIX,
    TMP_DIR,
)


router = APIRouter()
_ACTIVE_RUNS_LOCK = threading.RLock()
_ACTIVE_RUNS: dict[str, subprocess.Popen[str]] = {}


def _load_active_run_index() -> dict[str, int]:
    if not ACTIVE_RUNS_PATH.exists():
        return {}
    payload = json.loads(ACTIVE_RUNS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("active run index must be an object")
    return {str(key): int(value) for key, value in payload.items()}


def _save_active_run_index(index: dict[str, int]) -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_RUNS_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_temp_run_config(payload: dict[str, Any]) -> Path | None:
    project_config = payload.get("projectConfig")
    if not isinstance(project_config, dict):
        return None

    tmp_dir = ROOT / ".tmp" / "run_configs"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".yaml",
        prefix="run_config_",
        dir=tmp_dir,
        delete=False,
    ) as file:
        yaml.safe_dump(project_config, file, allow_unicode=True, sort_keys=False)
        return Path(file.name)


def _build_run_command(payload: dict[str, Any], *, config_path: Path | None = None) -> list[str]:
    run_overrides = payload.get("runOverrides")
    if not isinstance(run_overrides, dict):
        raise HTTPException(status_code=400, detail="runOverrides is required")

    topic = str(run_overrides.get("topic", "") or "").strip()
    user_request = str(run_overrides.get("user_request", "") or "").strip()
    resume_run_id = str(run_overrides.get("resume_run_id", "") or "").strip()

    if not topic and not resume_run_id:
        raise HTTPException(status_code=400, detail="topic or resume_run_id is required")

    command = [sys.executable, "-u", "scripts/run_agent.py"]

    if config_path is not None:
        command.extend(["--config", str(config_path)])

    if topic:
        command.extend(["--topic", topic])
    if user_request:
        command.extend(["--user_request", user_request])
    if resume_run_id:
        command.extend(["--resume-run-id", resume_run_id])

    option_map = {
        "output_dir": "--output_dir",
        "language": "--language",
        "model": "--model",
        "max_iter": "--max_iter",
        "papers_per_query": "--papers_per_query",
    }
    for key, flag in option_map.items():
        value = run_overrides.get(key)
        if value not in (None, ""):
            command.extend([flag, str(value)])

    sources = run_overrides.get("sources")
    if isinstance(sources, list) and sources:
        selected = [str(item).strip() for item in sources if str(item).strip()]
        if selected:
            command.extend(["--sources", ",".join(selected)])

    route_roles = run_overrides.get("route_roles")
    if isinstance(route_roles, list) and route_roles:
        selected_roles = [str(item).strip() for item in route_roles if str(item).strip()]
        if selected_roles:
            command.extend(["--route_roles", ",".join(selected_roles)])

    if bool(run_overrides.get("no_web", False)):
        command.append("--no-web")
    if bool(run_overrides.get("no_scrape", False)):
        command.append("--no-scrape")
    if bool(run_overrides.get("verbose", False)):
        command.append("--verbose")

    command.extend(["--mode", "os"])

    return command


def _resolve_run_output_dir(payload: dict[str, Any]) -> Path:
    run_overrides = payload.get("runOverrides")
    if not isinstance(run_overrides, dict):
        raise HTTPException(status_code=400, detail="runOverrides is required")
    raw_path = str(run_overrides.get("output_dir", "") or "").strip() or "outputs"
    output_dir = Path(raw_path)
    if not output_dir.is_absolute():
        output_dir = (ROOT / output_dir).resolve()
    return output_dir


def _collect_run_dirs(output_dir: Path) -> list[Path]:
    if not output_dir.exists():
        return []
    return [path for path in output_dir.glob("run_*") if path.is_dir()]


def _load_latest_run_state(output_dir: Path, known_run_dirs: set[str]) -> dict[str, Any] | None:
    candidates = [path for path in _collect_run_dirs(output_dir) if path.name not in known_run_dirs]
    if not candidates:
        return None

    latest_run_dir = max(candidates, key=lambda path: path.stat().st_mtime)
    state_path = latest_run_dir / "research_state.json"
    if not state_path.exists():
        return None

    with state_path.open("r", encoding="utf-8") as file:
        state = json.load(file)
    report_path = latest_run_dir / "research_report.md"
    report_text = ""
    if report_path.exists():
        report_text = report_path.read_text(encoding="utf-8")

    return {
        "run_id": state.get("run_id", ""),
        "status": state.get("status", ""),
        "route_plan": state.get("route_plan", {}),
        "role_status": state.get("role_status", {}),
        "await_experiment_results": bool(state.get("await_experiment_results", False)),
        "report_text": report_text,
    }


def _extract_structured_event(line: str) -> dict[str, Any] | None:
    marker = "event="
    idx = line.find(marker)
    if idx < 0:
        return None
    payload_text = line[idx + len(marker) :].strip()
    if not payload_text:
        return None
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
def _register_active_run(client_request_id: str, process: subprocess.Popen[str]) -> None:
    with _ACTIVE_RUNS_LOCK:
        _ACTIVE_RUNS[client_request_id] = process
        index = _load_active_run_index()
        index[client_request_id] = int(process.pid)
        _save_active_run_index(index)


def _unregister_active_run(client_request_id: str, process: subprocess.Popen[str] | None = None) -> None:
    with _ACTIVE_RUNS_LOCK:
        current = _ACTIVE_RUNS.get(client_request_id)
        if process is not None and current is not process:
            return
        _ACTIVE_RUNS.pop(client_request_id, None)
        index = _load_active_run_index()
        if client_request_id in index:
            index.pop(client_request_id, None)
            _save_active_run_index(index)


def _terminate_pid(pid: int, *, timeout_sec: float = 5.0) -> str:
    if pid <= 0:
        return "not_found"
    if platform.system() == "Windows":
        completed = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        if completed.returncode == 0:
            return "terminated"
        stderr = (completed.stderr or "").lower()
        stdout = (completed.stdout or "").lower()
        if "not found" in stderr or "not found" in stdout or "no running instance" in stderr or "no running instance" in stdout:
            return "already_exited"
        return "kill_failed"
    try:
        os.kill(pid, 15)
        return "terminated"
    except ProcessLookupError:
        return "already_exited"
    except OSError:
        return "kill_failed"


def _terminate_process(process: subprocess.Popen[str], *, timeout_sec: float = 5.0) -> str:
    if process.poll() is not None:
        return "already_exited"
    pid = int(getattr(process, "pid", 0) or 0)
    if pid > 0:
        result = _terminate_pid(pid, timeout_sec=timeout_sec)
        if result in {"terminated", "already_exited"}:
            return result
    process.terminate()
    try:
        process.wait(timeout=timeout_sec)
        return "terminated"
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            pass
        return "killed"


@router.post("/api/run/stop")
async def stop_run(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="stop payload must be an object")
    client_request_id = str(payload.get("client_request_id", "")).strip()
    if not client_request_id:
        raise HTTPException(status_code=400, detail="client_request_id is required")

    with _ACTIVE_RUNS_LOCK:
        process = _ACTIVE_RUNS.get(client_request_id)

    if process is not None:
        result = _terminate_process(process)
        _unregister_active_run(client_request_id, process)
        return {"status": result}

    index = _load_active_run_index()
    pid = int(index.get(client_request_id, 0) or 0)
    if pid <= 0:
        return {"status": "not_found"}

    result = _terminate_pid(pid)
    if result in {"terminated", "already_exited"}:
        with _ACTIVE_RUNS_LOCK:
            latest_index = _load_active_run_index()
            latest_index.pop(client_request_id, None)
            _save_active_run_index(latest_index)
    return {"status": result}


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

    runtime_config_path = _write_temp_run_config(payload)
    try:
        command = _build_run_command(payload, config_path=runtime_config_path)
        saved_credentials = _read_env_file()
        env = _merge_runtime_credentials(
            base_env=os.environ.copy(),
            saved_credentials=saved_credentials,
            request_credentials=payload.get("credentials"),
        )
        output_dir = _resolve_run_output_dir(payload)
        known_run_dirs = {path.name for path in _collect_run_dirs(output_dir)}
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )
    except Exception:
        if runtime_config_path is not None:
            runtime_config_path.unlink(missing_ok=True)
        raise
    _register_active_run(client_request_id, process)

    def generate_output():
        try:
            if process.stdout is None:
                raise RuntimeError("run process stdout pipe is unavailable")
            for line in process.stdout:
                event_payload = _extract_structured_event(line)
                if event_payload is not None:
                    yield f"{RUN_EVENT_PREFIX}{json.dumps(event_payload, ensure_ascii=False)}\n"
                    continue
                yield f"{RUN_LOG_PREFIX}{line.rstrip()}\n"
            exit_code = process.wait()
            run_state = _load_latest_run_state(output_dir, known_run_dirs)
            if run_state is not None:
                yield f"{RUN_STATE_PREFIX}{json.dumps(run_state, ensure_ascii=False)}\n"
                report_text = str(run_state.get("report_text", "") or "")
                if report_text.strip():
                    yield report_text
            if exit_code != 0:
                yield f"{RUN_LOG_PREFIX}[run_agent exited with code {exit_code}]\n"
        finally:
            if process.poll() is None:
                _terminate_process(process, timeout_sec=1.0)
            _unregister_active_run(client_request_id, process)
            if runtime_config_path is not None:
                runtime_config_path.unlink(missing_ok=True)
            if process.stdout is not None:
                process.stdout.close()

    return StreamingResponse(generate_output(), media_type="text/plain")
