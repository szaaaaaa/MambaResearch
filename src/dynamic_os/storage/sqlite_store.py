from __future__ import annotations

import json
import sqlite3
from src.dynamic_os.contracts.artifact import ArtifactRecord, now_iso as _now_iso
from src.dynamic_os.contracts.observation import ErrorType, NodeStatus, Observation
from src.dynamic_os.contracts.route_plan import RoleId, RoutePlan


def init_knowledge_db(sqlite_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(sqlite_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id    TEXT PRIMARY KEY,
            artifact_type  TEXT,
            producer_role  TEXT,
            producer_skill TEXT,
            schema_version TEXT,
            content_ref    TEXT,
            payload_json   TEXT,
            source_inputs_json TEXT,
            created_at     TEXT,
            run_id         TEXT
        );

        CREATE TABLE IF NOT EXISTS observations (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id                TEXT,
            role                   TEXT,
            status                 TEXT,
            error_type             TEXT,
            what_happened          TEXT,
            what_was_tried_json    TEXT,
            suggested_options_json TEXT,
            recommended_action     TEXT,
            produced_artifacts_json TEXT,
            confidence             REAL,
            duration_ms            REAL,
            run_id                 TEXT,
            created_at             TEXT
        );

        CREATE TABLE IF NOT EXISTS plans (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id             TEXT,
            planning_iteration INTEGER,
            payload_json       TEXT,
            created_at         TEXT
        );

        CREATE TABLE IF NOT EXISTS runs (
            id         TEXT PRIMARY KEY,
            topic      TEXT,
            created_at TEXT,
            status     TEXT
        );

        CREATE TABLE IF NOT EXISTS kg_nodes (
            id              TEXT PRIMARY KEY,
            node_type       TEXT,
            properties_json TEXT,
            embedding_id    TEXT,
            created_at      TEXT,
            run_id          TEXT
        );

        CREATE TABLE IF NOT EXISTS kg_edges (
            id              TEXT PRIMARY KEY,
            source_id       TEXT,
            target_id       TEXT,
            relation_type   TEXT,
            properties_json TEXT,
            created_at      TEXT,
            run_id          TEXT
        );

        CREATE TABLE IF NOT EXISTS skill_metrics (
            skill_id        TEXT PRIMARY KEY,
            execution_count INTEGER DEFAULT 0,
            success_count   INTEGER DEFAULT 0,
            fail_count      INTEGER DEFAULT 0,
            avg_duration_ms REAL    DEFAULT 0.0,
            utility_score   REAL    DEFAULT 0.5,
            updated_at      TEXT
        );

        CREATE TABLE IF NOT EXISTS research_memory (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          TEXT NOT NULL,
            user_request    TEXT,
            topics_json     TEXT,
            key_papers_json TEXT,
            methods_json    TEXT,
            findings_json   TEXT,
            quality_score   REAL,
            created_at      TEXT
        );

        CREATE TABLE IF NOT EXISTS user_profile (
            key             TEXT PRIMARY KEY,
            value_json      TEXT,
            updated_at      TEXT
        );
        """
    )
    return conn


def _row_to_artifact(row: sqlite3.Row) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=row["artifact_id"],
        artifact_type=row["artifact_type"],
        producer_role=RoleId(row["producer_role"]),
        producer_skill=row["producer_skill"],
        schema_version=row["schema_version"],
        content_ref=row["content_ref"],
        payload=json.loads(row["payload_json"]),
        source_inputs=json.loads(row["source_inputs_json"]),
        created_at=row["created_at"],
    )


def _row_to_observation(row: sqlite3.Row) -> Observation:
    role_raw = row["role"]
    role: RoleId | str = role_raw if role_raw == "planner" else RoleId(role_raw)
    return Observation(
        node_id=row["node_id"],
        role=role,
        status=NodeStatus(row["status"]),
        error_type=ErrorType(row["error_type"]),
        what_happened=row["what_happened"],
        what_was_tried=json.loads(row["what_was_tried_json"]),
        suggested_options=json.loads(row["suggested_options_json"]),
        recommended_action=row["recommended_action"],
        produced_artifacts=json.loads(row["produced_artifacts_json"]),
        confidence=row["confidence"],
        duration_ms=row["duration_ms"],
    )


class SqliteArtifactStore:
    def __init__(self, conn: sqlite3.Connection, run_id: str) -> None:
        self._conn = conn
        self._run_id = run_id

    def save(self, record: ArtifactRecord) -> None:
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
                record.producer_role.value,
                record.producer_skill,
                record.schema_version,
                record.content_ref,
                json.dumps(record.payload, ensure_ascii=False),
                json.dumps(record.source_inputs, ensure_ascii=False),
                record.created_at,
                self._run_id,
            ),
        )
        self._conn.commit()

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        row = self._conn.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_artifact(row)

    def list_by_type(self, artifact_type: str) -> list[ArtifactRecord]:
        rows = self._conn.execute(
            "SELECT * FROM artifacts WHERE artifact_type = ? AND run_id = ?",
            (artifact_type, self._run_id),
        ).fetchall()
        return [_row_to_artifact(r) for r in rows]

    def list_all(self) -> list[ArtifactRecord]:
        rows = self._conn.execute(
            "SELECT * FROM artifacts WHERE run_id = ?", (self._run_id,)
        ).fetchall()
        return [_row_to_artifact(r) for r in rows]

    def summary(self) -> list[dict[str, str]]:
        return [
            {
                "artifact_id": record.artifact_id,
                "artifact_type": record.artifact_type,
                "artifact_ref": f"artifact:{record.artifact_type}:{record.artifact_id}",
                "producer_role": record.producer_role.value,
            }
            for record in self.list_all()
        ]


class SqliteObservationStore:
    def __init__(self, conn: sqlite3.Connection, run_id: str) -> None:
        self._conn = conn
        self._run_id = run_id

    def save(self, obs: Observation) -> None:
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
        rows = self._conn.execute(
            "SELECT * FROM observations WHERE run_id = ? ORDER BY id DESC LIMIT ?",
            (self._run_id, n),
        ).fetchall()
        return [_row_to_observation(r) for r in rows]

    def list_by_node(self, node_id: str) -> list[Observation]:
        rows = self._conn.execute(
            "SELECT * FROM observations WHERE node_id = ? AND run_id = ?",
            (node_id, self._run_id),
        ).fetchall()
        return [_row_to_observation(r) for r in rows]


class SqlitePlanStore:
    def __init__(self, conn: sqlite3.Connection, run_id: str) -> None:
        self._conn = conn
        self._run_id = run_id

    def save(self, plan: RoutePlan) -> None:
        self._conn.execute(
            """
            INSERT INTO plans (run_id, planning_iteration, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                self._run_id,
                plan.planning_iteration,
                json.dumps(plan.model_dump(mode="json"), ensure_ascii=False),
                _now_iso(),
            ),
        )
        self._conn.commit()

    def get_latest(self) -> RoutePlan | None:
        row = self._conn.execute(
            "SELECT * FROM plans WHERE run_id = ? ORDER BY id DESC LIMIT 1",
            (self._run_id,),
        ).fetchone()
        if row is None:
            return None
        return RoutePlan.model_validate(json.loads(row["payload_json"]))

    def list_all(self) -> list[RoutePlan]:
        rows = self._conn.execute(
            "SELECT * FROM plans WHERE run_id = ? ORDER BY id ASC",
            (self._run_id,),
        ).fetchall()
        return [RoutePlan.model_validate(json.loads(r["payload_json"])) for r in rows]
