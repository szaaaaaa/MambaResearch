"""一次性清理脚本：删除 segments + messages 都为空的 conversations 行。

用途
----
2026-04-29 asset-centric UI pivot 之后，旧"会话为中心"模型留下的空 conversation
（用户点过 "+ 新建会话" 但从未发消息的）在新 UI 里仅出现在草稿箱，且没有
内容可继续——属于纯噪音。本脚本一次性清掉它们。

幂等：再跑一次不报错也不误删（empty 条件确定，无内容的对话仍是 empty）。

默认作用域
~~~~~~~~~~
默认仅清理 ``projects.json`` 里 ``active_project_id`` 对应的项目。这能避免
误删其他（archived / 被遗忘的）项目下的空对话。带 ``--all-projects`` 可
跨所有 project 清理。带 ``--project-id <id>`` 可指定其他项目。

用法
----
    python scripts/cleanup_empty_conversations.py [--dry-run]
                                                  [--db-path PATH]
                                                  [--projects-json PATH]
                                                  [--project-id ID | --all-projects]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


_DEFAULT_DB_PATH = Path.home() / ".mambaresearch" / "mamba.db"
_DEFAULT_PROJECTS_JSON = Path.home() / ".mambaresearch" / "projects.json"


def read_active_project_id(projects_json: Path) -> str | None:
    if not projects_json.exists():
        return None
    try:
        payload = json.loads(projects_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    pid = payload.get("active_project_id")
    return pid if isinstance(pid, str) else None


def find_empty_conversations(
    conn: sqlite3.Connection, *, project_id: str | None
) -> list[tuple[str, str, str]]:
    """返回 (id, title, project_id) 列表，命中条件：
    - conversation_segments 表中无该 conversation_id 的行
    - messages 表中无该 conversation_id 的行
    - ``project_id`` 给定时只返回该项目；``None`` 时跨所有 project
    """
    cur = conn.cursor()
    where_proj = "AND c.project_id = ?" if project_id is not None else ""
    params: list = []
    if project_id is not None:
        params.append(project_id)
    cur.execute(
        f"""
        SELECT c.id, COALESCE(c.title, ''), c.project_id
        FROM conversations c
        WHERE NOT EXISTS (
            SELECT 1 FROM conversation_segments s WHERE s.conversation_id = c.id
        )
        AND NOT EXISTS (
            SELECT 1 FROM messages m WHERE m.conversation_id = c.id
        )
        {where_proj}
        ORDER BY c.created_at ASC
        """,
        params,
    )
    rows = cur.fetchall()
    cur.close()
    return [(row[0], row[1], row[2]) for row in rows]


def delete_conversations(conn: sqlite3.Connection, ids: list[str]) -> int:
    if not ids:
        return 0
    cur = conn.cursor()
    placeholders = ",".join("?" * len(ids))
    cur.execute(
        f"DELETE FROM conversations WHERE id IN ({placeholders})",
        ids,
    )
    removed = cur.rowcount
    conn.commit()
    cur.close()
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=_DEFAULT_DB_PATH,
        help=f"mamba.db 路径（默认 {_DEFAULT_DB_PATH}）",
    )
    parser.add_argument(
        "--projects-json",
        type=Path,
        default=_DEFAULT_PROJECTS_JSON,
        help=f"projects.json 路径（默认 {_DEFAULT_PROJECTS_JSON}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印将要删除的 conversations，不做实际删除",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--project-id",
        type=str,
        default=None,
        help="指定 project_id（默认从 projects.json 读 active）",
    )
    scope.add_argument(
        "--all-projects",
        action="store_true",
        help="跨所有 project 清理（不推荐，慎用）",
    )
    args = parser.parse_args(argv)

    db_path: Path = args.db_path
    if not db_path.exists():
        print(f"[skip] DB 不存在：{db_path}", file=sys.stderr)
        return 0

    if args.all_projects:
        scope_label = "全部 project（--all-projects）"
        target_project_id = None
    elif args.project_id:
        scope_label = f"project_id={args.project_id}"
        target_project_id = args.project_id
    else:
        target_project_id = read_active_project_id(args.projects_json)
        if target_project_id is None:
            print(
                f"[skip] 未能从 {args.projects_json} 读到 active_project_id；"
                f"如需跨所有 project 清理请加 --all-projects。",
                file=sys.stderr,
            )
            return 0
        scope_label = f"active project_id={target_project_id}"

    conn = sqlite3.connect(str(db_path))
    try:
        empties = find_empty_conversations(conn, project_id=target_project_id)
        if not empties:
            print(f"[ok] 无空 conversation 可清理（DB={db_path}, scope={scope_label}）")
            return 0

        print(f"[found] {len(empties)} 个空 conversation（scope={scope_label}）：")
        for cid, title, pid in empties:
            print(f"  - {cid[:12]}...  title={title!r}  project={pid[:8]}...")

        if args.dry_run:
            print("[dry-run] 未删除。去掉 --dry-run 即执行删除。")
            return 0

        removed = delete_conversations(conn, [cid for cid, _, _ in empties])
        print(f"[done] 已删除 {removed} 行。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
