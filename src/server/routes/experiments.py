"""只读科研实验记录；执行、进程状态与取消由 Codex 提供。"""
import json

from fastapi import APIRouter, HTTPException

from src.server.projects.db import get_db
from src.server.projects.registry import get_registry

router = APIRouter()


def _project_id():
    project = get_registry().get_active()
    if project is None:
        raise HTTPException(status_code=409, detail="请选择实验所属项目")
    return project.id


def _record(row):
    return {"run_id": row["id"], "status": row["status"], "exit_code": row["exit_code"],
            "script_path": row["script_path"], "started_at": row["started_at"], "ended_at": row["ended_at"],
            "elapsed_s": row["ended_at"] - row["started_at"] if row["ended_at"] is not None else None,
            "log_lines": row["log_count"], "metrics_count": row["metric_count"],
            "last_metric": json.loads(row["last_metric_json"]) if row["last_metric_json"] else None}


@router.get("/api/experiments")
def list_runs():
    project_id = _project_id()
    with get_db().cursor() as cursor:
        rows = cursor.execute("SELECT * FROM experiment_runs WHERE project_id=? ORDER BY started_at DESC,rowid DESC LIMIT 50", (project_id,)).fetchall()
    return {"runs": [_record(row) for row in rows]}


@router.get("/api/experiments/{run_id}")
def snapshot(run_id: str):
    project_id = _project_id()
    with get_db().cursor() as cursor:
        row = cursor.execute("SELECT * FROM experiment_runs WHERE id=? AND project_id=?", (run_id, project_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="该项目没有此实验记录")
        logs = cursor.execute("SELECT payload FROM (SELECT sequence,payload FROM experiment_events WHERE run_id=? AND kind='log' ORDER BY sequence DESC LIMIT 200) ORDER BY sequence", (run_id,)).fetchall()
        metrics = cursor.execute("SELECT payload FROM experiment_events WHERE run_id=? AND kind='metric' ORDER BY sequence", (run_id,)).fetchall()
    return {"status": _record(row), "logs": [json.loads(item[0]) for item in logs],
            "metrics": [json.loads(item[0]) for item in metrics]}
