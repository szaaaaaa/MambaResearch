"""Durable user-requested research tasks; Codex App owns execution."""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from uuid import uuid4

from src.server.projects.db import get_db
from src.server.projects.registry import get_registry


def prepare_task(project_id: str, prompt: str, conversation_id: str | None = None) -> dict:
    project = get_registry().get_project(project_id)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 64000:
        raise ValueError("任务内容必须是 1–64000 字符的非空文本")
    task_id, nonce = uuid4().hex, secrets.token_hex(16)
    now = int(time.time())
    with get_db().cursor() as cursor:
        if conversation_id is not None:
            row = cursor.execute("SELECT project_id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if row is None or row[0] != project_id:
                raise ValueError("研究记录不属于本次项目")
        else:
            conversation_id = uuid4().hex
            cursor.execute(
                "INSERT INTO conversations(id,project_id,title,backend,created_at,last_active_at) VALUES (?,?,?,'codex_app',?,?)",
                (conversation_id, project_id, prompt.strip()[:80], now, now),
            )
        cursor.execute(
            "INSERT INTO workbench_tasks(id,project_id,project_path,conversation_id,prompt,nonce,status,created_at) "
            "VALUES (?,?,?,?,?,?,'waiting',?)",
            (task_id, project_id, project.path, conversation_id, prompt.strip(), nonce, now),
        )
        cursor.execute(
            "INSERT INTO messages(id,conversation_id,role,text,served_by,created_at) VALUES (?,?,'user',?,'user',?)",
            (uuid4().hex, conversation_id, prompt.strip(), now),
        )
    message = (
        f"科研工作台任务：{prompt.strip()}\n\n"
        f"固定项目上下文：{json.dumps({'project_id': project.id, 'project_path': project.path}, ensure_ascii=False)}\n"
        f"关联研究记录：{conversation_id}。需要旧结论时可用 mamba_history 查询此记录。\n"
        "所有科研 MCP 调用必须传上述 project_id；Workspace 还须传上述 project_path。"
        "科研产物写在该项目 outputs/<run_id>/；保持原始研究文件不变。\n"
        f"完成或遇到无法继续的问题后，调用 mamba_workbench 的 record_task_result，task_id={task_id}，"
        f"nonce={nonce}，status=completed 或 error，summary=实际结果，artifacts=相对项目目录的产物路径列表。"
        "不要在执行前记录完成。"
    )
    return {"task_id": task_id, "conversation_id": conversation_id, "message": message}


def list_tasks(project_id: str) -> list[dict]:
    get_registry().get_project(project_id)
    with get_db().cursor() as cursor:
        rows = cursor.execute(
            "SELECT id,project_id,project_path,conversation_id,prompt,status,summary,artifacts_json,created_at,finished_at "
            "FROM workbench_tasks WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT 50", (project_id,),
        ).fetchall()
    return [{**dict(row), "artifacts": json.loads(row["artifacts_json"])} for row in rows]


def record_result(task_id: str, nonce: str, status: str, summary: str, artifacts: list[str]) -> dict:
    if status not in {"completed", "error"} or not isinstance(summary, str) or not summary.strip():
        raise ValueError("status 必须为 completed/error，summary 必须是非空实际结果")
    if not isinstance(artifacts, list) or any(not isinstance(path, str) for path in artifacts):
        raise ValueError("artifacts 必须是相对项目目录的路径数组")
    with get_db().cursor() as cursor:
        row = cursor.execute("SELECT * FROM workbench_tasks WHERE id=?", (task_id,)).fetchone()
        if row is None or not isinstance(nonce, str) or not secrets.compare_digest(row["nonce"], nonce):
            raise ValueError("未知任务或确认 nonce 不匹配")
        encoded = json.dumps(artifacts, ensure_ascii=False)
        if row["status"] != "waiting":
            if (row["status"], row["summary"], row["artifacts_json"]) != (status, summary.strip(), encoded):
                raise ValueError("任务已有最终结果，不能覆盖")
            return {"task_id": task_id, "status": status}
        root = Path(row["project_path"]).resolve()
        for artifact in artifacts:
            target = (root / artifact).resolve()
            if Path(artifact).anchor or not target.is_relative_to(root / "outputs") or not target.is_file():
                raise ValueError("产物必须是项目 outputs 目录内已存在的文件")
        now = int(time.time())
        cursor.execute("UPDATE workbench_tasks SET status=?,summary=?,artifacts_json=?,finished_at=? WHERE id=?",
                       (status, summary.strip(), encoded, now, task_id))
        cursor.execute(
            "INSERT INTO messages(id,conversation_id,role,text,served_by,tool_use_summary,created_at) "
            "VALUES (?,?,'assistant',?,'codex_app',?,?)",
            (uuid4().hex, row["conversation_id"], summary.strip(), encoded, now),
        )
        cursor.execute("UPDATE conversations SET last_active_at=? WHERE id=?", (now, row["conversation_id"]))
    return {"task_id": task_id, "status": status}
