"""项目级 mamba.db 级联清理 —— delete_project 时调用。

设计取舍
~~~~~~~~
schema 没声明 ``ON DELETE CASCADE``（v1 写时 SQLite 还允许无 FK 表关联）。
所以删 project 时孤儿数据不会自动清。本模块给一个**显式**清理入口，按
依赖顺序删表，单事务保证原子性：

    messages → mcp_calls → conversation_segments → conversations → experiment_runs

物理目录 + workspace ``.mambaresearch/`` 不动 —— 仍按 plan 决定保留。
backend 自己的 JSONL（``~/.claude/projects/...`` / ``~/.codex/sessions/...``）
也不动。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.server.projects.db import get_db


@dataclass
class CleanupSummary:
    """清理执行统计——返给 caller / API 客户端做透明度展示。"""

    conversations: int
    conversation_segments: int
    messages: int
    mcp_calls: int
    experiment_runs: int

    def to_dict(self) -> dict[str, int]:
        return {
            "conversations": self.conversations,
            "conversation_segments": self.conversation_segments,
            "messages": self.messages,
            "mcp_calls": self.mcp_calls,
            "experiment_runs": self.experiment_runs,
        }


def cleanup_project_data(project_id: str) -> CleanupSummary:
    """删 mamba.db 中所有 ``project_id`` 关联的行。

    返回各表删除条数。被调用方应在 ``registry.delete_project`` 前调，避免
    project 已从 registry 移除后再 cleanup 失败导致 orphan 半残（registry
    操作不可回滚）。

    单事务：``MambaDb.cursor()`` 退出时统一 commit；中途异常 rollback，
    所有行保持不动。
    """
    with get_db().cursor() as cur:
        # 1. 先拿到本 project 下所有 conversation_id —— 后续删 messages /
        #    segments / mcp_calls 都靠这个列表过滤
        cur.execute(
            "SELECT id FROM conversations WHERE project_id = ?", (project_id,)
        )
        conv_ids = [row["id"] for row in cur.fetchall()]

        msgs_deleted = 0
        segs_deleted = 0
        mcp_deleted = 0
        if conv_ids:
            placeholders = ",".join("?" for _ in conv_ids)

            # 2. messages —— v3.3 mirror，删了不影响 backend JSONL
            cur.execute(
                f"DELETE FROM messages WHERE conversation_id IN ({placeholders})",
                conv_ids,
            )
            msgs_deleted = cur.rowcount or 0

            # 3. mcp_calls —— Stage 3 工具调用历史
            cur.execute(
                f"DELETE FROM mcp_calls WHERE conversation_id IN ({placeholders})",
                conv_ids,
            )
            mcp_deleted = cur.rowcount or 0

            # 4. conversation_segments —— backend ↔ conversation 关联
            cur.execute(
                f"DELETE FROM conversation_segments WHERE conversation_id IN ({placeholders})",
                conv_ids,
            )
            segs_deleted = cur.rowcount or 0

        # 5. conversations 本身
        cur.execute("DELETE FROM conversations WHERE project_id = ?", (project_id,))
        convs_deleted = cur.rowcount or 0

        # 6. experiment_runs —— Stage 4 实验子进程登记表，按 project_id 直接删
        cur.execute(
            "DELETE FROM experiment_runs WHERE project_id = ?", (project_id,)
        )
        runs_deleted = cur.rowcount or 0

    return CleanupSummary(
        conversations=convs_deleted,
        conversation_segments=segs_deleted,
        messages=msgs_deleted,
        mcp_calls=mcp_deleted,
        experiment_runs=runs_deleted,
    )
