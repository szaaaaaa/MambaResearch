"""SQLite 持久化存储 —— 制品、观测、计划的关系型存储后端。

本模块承担两项职责：

1. **数据库初始化** (``init_knowledge_db``)
   创建系统所需的全部 SQLite 表，包括制品、观测、计划、运行记录、
   知识图谱节点/边、技能指标、研究记忆、用户画像等。

2. **核心存储实现** (``SqliteArtifactStore``, ``SqliteObservationStore``, ``SqlitePlanStore``)
   分别实现 ``memory.py`` 中定义的三个 Protocol 接口的 SQLite 版本，
   提供跨进程 / 跨运行的数据持久化能力。

表结构概览
----------
- ``artifacts``: 制品记录，按 run_id 隔离
- ``observations``: 节点执行观测，自增 ID 保证时序
- ``plans``: 执行计划版本，JSON 序列化存储
- ``runs``: 运行元数据（ID、主题、状态）
- ``kg_nodes`` / ``kg_edges``: 知识图谱节点和边
- ``skill_metrics``: 技能效用指标
- ``research_memory``: 跨运行研究记忆
- ``user_profile``: 用户画像键值对
"""

from __future__ import annotations

import json
import sqlite3
from src.dynamic_os.contracts.artifact import ArtifactRecord, now_iso as _now_iso
from src.dynamic_os.contracts.observation import ErrorType, NodeStatus, Observation
from src.dynamic_os.contracts.route_plan import RoleId, RoutePlan


def init_knowledge_db(sqlite_path: str) -> sqlite3.Connection:
    """初始化 SQLite 数据库并创建所有必需的表。

    使用 ``CREATE TABLE IF NOT EXISTS`` 保证幂等，可安全重复调用。

    参数
    ----------
    sqlite_path : str
        SQLite 数据库文件路径。若不存在会自动创建。

    返回
    -------
    sqlite3.Connection
        已建表、启用 Row 工厂的数据库连接。
    """
    conn = sqlite3.connect(sqlite_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # 启用按列名访问
    conn.executescript(
        """
        -- 制品表：存储技能产出的结构化数据
        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id    TEXT PRIMARY KEY,  -- 制品唯一标识
            artifact_type  TEXT,              -- 制品类型（TopicBrief / SearchPlan / SourceSet 等）
            producer_role  TEXT,              -- 生产者角色 ID
            producer_skill TEXT,              -- 生产者技能 ID
            schema_version TEXT,              -- 数据模式版本
            content_ref    TEXT,              -- 内容引用路径
            payload_json   TEXT,              -- 制品主体数据（JSON）
            source_inputs_json TEXT,          -- 输入来源引用列表（JSON）
            created_at     TEXT,              -- 创建时间（ISO 8601）
            run_id         TEXT               -- 所属运行 ID
        );

        -- 观测表：记录每个计划节点的执行结果
        CREATE TABLE IF NOT EXISTS observations (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自增主键，保证时序
            node_id                TEXT,       -- 关联的计划节点 ID
            role                   TEXT,       -- 执行角色
            status                 TEXT,       -- 执行状态（success / failed / partial 等）
            error_type             TEXT,       -- 错误类型
            what_happened          TEXT,       -- 执行概况描述
            what_was_tried_json    TEXT,       -- 尝试过的操作列表（JSON）
            suggested_options_json TEXT,       -- 建议的后续选项（JSON）
            recommended_action     TEXT,       -- 推荐的下一步动作
            produced_artifacts_json TEXT,      -- 产出的制品 ID 列表（JSON）
            confidence             REAL,       -- 结果置信度（0~1）
            duration_ms            REAL,       -- 执行耗时（毫秒）
            run_id                 TEXT,       -- 所属运行 ID
            created_at             TEXT        -- 记录时间
        );

        -- 计划表：存储 RoutePlan 的版本历史
        CREATE TABLE IF NOT EXISTS plans (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自增主键
            run_id             TEXT,       -- 所属运行 ID
            planning_iteration INTEGER,   -- 规划迭代轮次
            payload_json       TEXT,       -- RoutePlan 完整序列化（JSON）
            created_at         TEXT        -- 创建时间
        );

        -- 运行记录表：每次研究任务的元数据
        CREATE TABLE IF NOT EXISTS runs (
            id         TEXT PRIMARY KEY,   -- 运行唯一 ID
            topic      TEXT,               -- 研究主题
            created_at TEXT,               -- 创建时间
            status     TEXT                -- 运行状态
        );

        -- 知识图谱节点表
        CREATE TABLE IF NOT EXISTS kg_nodes (
            id              TEXT PRIMARY KEY,  -- 节点唯一 ID
            node_type       TEXT,              -- 节点类型（Paper / Concept / Method 等）
            properties_json TEXT,              -- 节点属性（JSON）
            embedding_id    TEXT,              -- 关联的向量嵌入 ID
            created_at      TEXT,              -- 创建时间
            run_id          TEXT               -- 来源运行 ID
        );

        -- 知识图谱边表
        CREATE TABLE IF NOT EXISTS kg_edges (
            id              TEXT PRIMARY KEY,  -- 边 ID（格式: source__relation__target）
            source_id       TEXT,              -- 源节点 ID
            target_id       TEXT,              -- 目标节点 ID
            relation_type   TEXT,              -- 关系类型（USES / CITES 等）
            properties_json TEXT,              -- 边属性（JSON）
            created_at      TEXT,              -- 创建时间
            run_id          TEXT               -- 来源运行 ID
        );

        -- 技能指标表：追踪各技能的执行统计和效用评分
        CREATE TABLE IF NOT EXISTS skill_metrics (
            skill_id        TEXT PRIMARY KEY,  -- 技能唯一 ID
            execution_count INTEGER DEFAULT 0, -- 累计执行次数
            success_count   INTEGER DEFAULT 0, -- 累计成功次数
            fail_count      INTEGER DEFAULT 0, -- 累计失败次数
            avg_duration_ms REAL    DEFAULT 0.0, -- 平均执行耗时
            utility_score   REAL    DEFAULT 0.5, -- 效用评分（EMA）
            updated_at      TEXT               -- 最后更新时间
        );

        -- 研究记忆表：跨运行的研究成果沉淀
        CREATE TABLE IF NOT EXISTS research_memory (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          TEXT NOT NULL,      -- 来源运行 ID
            user_request    TEXT,               -- 用户原始请求
            topics_json     TEXT,               -- 涉及主题列表（JSON）
            key_papers_json TEXT,               -- 关键论文列表（JSON）
            methods_json    TEXT,               -- 涉及方法列表（JSON）
            findings_json   TEXT,               -- 主要发现列表（JSON）
            quality_score   REAL,               -- 运行质量评分
            created_at      TEXT                -- 创建时间
        );

        -- 用户画像表：存储用户偏好和行为特征
        CREATE TABLE IF NOT EXISTS user_profile (
            key             TEXT PRIMARY KEY,   -- 画像键名
            value_json      TEXT,               -- 画像值（JSON）
            updated_at      TEXT                -- 最后更新时间
        );
        """
    )
    return conn


# ---------------------------------------------------------------------------
# 行转换辅助函数
# ---------------------------------------------------------------------------


def _row_to_artifact(row: sqlite3.Row) -> ArtifactRecord:
    """将 SQLite 行数据转换为 ArtifactRecord 数据模型。"""
    return ArtifactRecord(
        artifact_id=row["artifact_id"],
        artifact_type=row["artifact_type"],
        producer_role=RoleId(row["producer_role"]),  # 字符串还原为枚举
        producer_skill=row["producer_skill"],
        schema_version=row["schema_version"],
        content_ref=row["content_ref"],
        payload=json.loads(row["payload_json"]),             # JSON 反序列化
        source_inputs=json.loads(row["source_inputs_json"]),  # JSON 反序列化
        created_at=row["created_at"],
    )


def _row_to_observation(row: sqlite3.Row) -> Observation:
    """将 SQLite 行数据转换为 Observation 数据模型。

    注意 role 字段的特殊处理：planner 角色以字符串形式存储，
    其他角色存储为 RoleId 枚举值。
    """
    role_raw = row["role"]
    # planner 是特殊角色，不属于 RoleId 枚举
    role: RoleId | str = role_raw if role_raw == "planner" else RoleId(role_raw)
    return Observation(
        node_id=row["node_id"],
        role=role,
        status=NodeStatus(row["status"]),           # 字符串还原为状态枚举
        error_type=ErrorType(row["error_type"]),     # 字符串还原为错误类型枚举
        what_happened=row["what_happened"],
        what_was_tried=json.loads(row["what_was_tried_json"]),
        suggested_options=json.loads(row["suggested_options_json"]),
        recommended_action=row["recommended_action"],
        produced_artifacts=json.loads(row["produced_artifacts_json"]),
        confidence=row["confidence"],
        duration_ms=row["duration_ms"],
    )


# ---------------------------------------------------------------------------
# SQLite 制品存储
# ---------------------------------------------------------------------------


class SqliteArtifactStore:
    """基于 SQLite 的制品持久化存储。

    所有查询操作自动按 run_id 过滤，保证运行间数据隔离。

    参数
    ----------
    conn : sqlite3.Connection
        数据库连接。
    run_id : str
        当前运行 ID，用于数据隔离。
    """

    def __init__(self, conn: sqlite3.Connection, run_id: str) -> None:
        self._conn = conn      # SQLite 连接
        self._run_id = run_id  # 当前运行 ID

    def save(self, record: ArtifactRecord) -> None:
        """保存制品记录，ID 冲突时覆盖更新。"""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO artifacts
                (artifact_id, artifact_type, producer_role, producer_skill,
                 schema_version, content_ref, payload_json, source_inputs_json,
                 created_at, run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.artifact_id,
                record.artifact_type,
                record.producer_role.value,  # 枚举转为字符串存储
                record.producer_skill,
                record.schema_version,
                record.content_ref,
                json.dumps(record.payload, ensure_ascii=False),        # 序列化 payload
                json.dumps(record.source_inputs, ensure_ascii=False),  # 序列化输入引用
                record.created_at,
                self._run_id,
            ),
        )
        self._conn.commit()

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        """根据 ID 查询单条制品，不限 run_id（支持跨运行引用）。"""
        row = self._conn.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_artifact(row)

    def list_by_type(self, artifact_type: str) -> list[ArtifactRecord]:
        """列出当前运行中指定类型的全部制品。"""
        rows = self._conn.execute(
            "SELECT * FROM artifacts WHERE artifact_type = ? AND run_id = ?",
            (artifact_type, self._run_id),
        ).fetchall()
        return [_row_to_artifact(r) for r in rows]

    def list_all(self) -> list[ArtifactRecord]:
        """列出当前运行的全部制品。"""
        rows = self._conn.execute(
            "SELECT * FROM artifacts WHERE run_id = ?", (self._run_id,)
        ).fetchall()
        return [_row_to_artifact(r) for r in rows]

    def summary(self) -> list[dict[str, str]]:
        """生成当前运行制品的摘要列表。"""
        return [
            {
                "artifact_id": record.artifact_id,
                "artifact_type": record.artifact_type,
                "artifact_ref": f"artifact:{record.artifact_type}:{record.artifact_id}",
                "producer_role": record.producer_role.value,
            }
            for record in self.list_all()
        ]


# ---------------------------------------------------------------------------
# SQLite 观测存储
# ---------------------------------------------------------------------------


class SqliteObservationStore:
    """基于 SQLite 的观测记录持久化存储。

    观测按自增 ID 排序，list_latest 使用倒序查询获取最新记录。

    参数
    ----------
    conn : sqlite3.Connection
        数据库连接。
    run_id : str
        当前运行 ID。
    """

    def __init__(self, conn: sqlite3.Connection, run_id: str) -> None:
        self._conn = conn
        self._run_id = run_id

    def save(self, obs: Observation) -> None:
        """持久化一条观测记录。"""
        # planner 角色直接用字符串，其他角色取枚举值
        role_value = obs.role if obs.role == "planner" else obs.role.value
        self._conn.execute(
            """
            INSERT INTO observations
                (node_id, role, status, error_type, what_happened,
                 what_was_tried_json, suggested_options_json, recommended_action,
                 produced_artifacts_json, confidence, duration_ms, run_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                obs.node_id,
                role_value,
                obs.status.value,
                obs.error_type.value,
                obs.what_happened,
                json.dumps(obs.what_was_tried, ensure_ascii=False),
                json.dumps(obs.suggested_options, ensure_ascii=False),
                obs.recommended_action,
                json.dumps(obs.produced_artifacts, ensure_ascii=False),
                obs.confidence,
                obs.duration_ms,
                self._run_id,
                _now_iso(),
            ),
        )
        self._conn.commit()

    def list_latest(self, n: int = 5) -> list[Observation]:
        """获取当前运行最近 n 条观测（按时间倒序）。"""
        rows = self._conn.execute(
            "SELECT * FROM observations WHERE run_id = ? ORDER BY id DESC LIMIT ?",
            (self._run_id, n),
        ).fetchall()
        return [_row_to_observation(r) for r in rows]

    def list_by_node(self, node_id: str) -> list[Observation]:
        """获取指定计划节点在当前运行中的全部观测。"""
        rows = self._conn.execute(
            "SELECT * FROM observations WHERE node_id = ? AND run_id = ?",
            (node_id, self._run_id),
        ).fetchall()
        return [_row_to_observation(r) for r in rows]


# ---------------------------------------------------------------------------
# SQLite 计划存储
# ---------------------------------------------------------------------------


class SqlitePlanStore:
    """基于 SQLite 的执行计划持久化存储。

    RoutePlan 通过 Pydantic 的 ``model_dump`` 序列化为 JSON 存储，
    读取时通过 ``model_validate`` 反序列化还原。

    参数
    ----------
    conn : sqlite3.Connection
        数据库连接。
    run_id : str
        当前运行 ID。
    """

    def __init__(self, conn: sqlite3.Connection, run_id: str) -> None:
        self._conn = conn
        self._run_id = run_id

    def save(self, plan: RoutePlan) -> None:
        """保存一个新版本的执行计划。"""
        self._conn.execute(
            """
            INSERT INTO plans (run_id, planning_iteration, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                self._run_id,
                plan.planning_iteration,
                # 使用 Pydantic 序列化，ensure_ascii=False 保留中文
                json.dumps(plan.model_dump(mode="json"), ensure_ascii=False),
                _now_iso(),
            ),
        )
        self._conn.commit()

    def get_latest(self) -> RoutePlan | None:
        """获取当前运行的最新计划版本。"""
        row = self._conn.execute(
            "SELECT * FROM plans WHERE run_id = ? ORDER BY id DESC LIMIT 1",
            (self._run_id,),
        ).fetchone()
        if row is None:
            return None
        # 从 JSON 反序列化还原 RoutePlan 模型
        return RoutePlan.model_validate(json.loads(row["payload_json"]))

    def list_all(self) -> list[RoutePlan]:
        """按创建顺序列出当前运行的全部计划版本。"""
        rows = self._conn.execute(
            "SELECT * FROM plans WHERE run_id = ? ORDER BY id ASC",
            (self._run_id,),
        ).fetchall()
        return [RoutePlan.model_validate(json.loads(r["payload_json"])) for r in rows]
