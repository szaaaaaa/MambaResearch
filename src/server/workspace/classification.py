"""``classification.db`` SQLite schema + CRUD。

数据布局
~~~~~~~~
``<project_path>/.mambaresearch/classification.db`` —— 每个 project 独立。

Schema
~~~~~~
单表 ``files``，path 主键，存 sha256/mtime/size 用于增量扫描判重；
分类结果含 primary_bucket / subtype / summary / tags / confidence /
user_override / classifier_model / classified_at。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


PRIMARY_BUCKETS = frozenset(
    {"experiment", "literature", "dataset", "idea", "unknown"}
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime INTEGER NOT NULL,
    primary_bucket TEXT NOT NULL CHECK (
        primary_bucket IN ('experiment', 'literature', 'dataset', 'idea', 'unknown')
    ),
    subtype TEXT,
    summary TEXT,
    tags TEXT,
    confidence REAL DEFAULT 0.0,
    user_override INTEGER DEFAULT 0,
    classified_at INTEGER NOT NULL,
    classifier_model TEXT
);
CREATE INDEX IF NOT EXISTS idx_files_bucket ON files(primary_bucket, mtime DESC);
CREATE INDEX IF NOT EXISTS idx_files_subtype ON files(subtype);
"""


@dataclass
class FileEntry:
    path: str
    sha256: str
    size: int
    mtime: int
    primary_bucket: str = "unknown"
    subtype: str | None = None
    summary: str | None = None
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.0
    user_override: bool = False
    classified_at: int = 0
    classifier_model: str | None = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size": self.size,
            "mtime": self.mtime,
            "primary_bucket": self.primary_bucket,
            "subtype": self.subtype,
            "summary": self.summary,
            "tags": list(self.tags),
            "confidence": self.confidence,
            "user_override": self.user_override,
            "classified_at": self.classified_at,
            "classifier_model": self.classifier_model,
        }


@dataclass
class ClassificationStats:
    total: int
    by_bucket: dict[str, int]
    last_classified_at: int | None
    user_override_count: int

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "by_bucket": dict(self.by_bucket),
            "last_classified_at": self.last_classified_at,
            "user_override_count": self.user_override_count,
        }


class ClassificationDb:
    """单 project 的分类索引。"""

    def __init__(self, project_path: Path | str) -> None:
        self._project_path = Path(project_path)
        self._db_path = self._project_path / ".mambaresearch" / "classification.db"
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                self._db_path.parent.mkdir(parents=True, exist_ok=True)
                self._conn = sqlite3.connect(
                    str(self._db_path),
                    check_same_thread=False,
                    isolation_level=None,
                )
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("PRAGMA journal_mode = WAL")
                self._conn.executescript(_SCHEMA)
            return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        conn = self.connect()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    # ---------- CRUD ----------

    def upsert_file(
        self, entry: FileEntry, *, respect_override: bool = True
    ) -> bool:
        """插入或更新一行。``respect_override=True`` 时若现有行 user_override=1
        则**不覆盖** primary_bucket / subtype / tags（仍刷新 sha256/mtime/size）。

        Returns
        -------
        bool
            True 如果实际写入了新行 / 更新了分类字段；False 如果由于 user_override
            保护而仅刷新了文件指纹。
        """
        if entry.primary_bucket not in PRIMARY_BUCKETS:
            raise ValueError(f"invalid primary_bucket: {entry.primary_bucket!r}")
        if entry.classified_at == 0:
            entry.classified_at = int(time.time())

        existing = self.get_file(entry.path)
        if existing is not None and existing.user_override and respect_override:
            # 仅刷新文件指纹，分类字段保留用户校正
            with self.cursor() as cur:
                cur.execute(
                    "UPDATE files SET sha256=?, size=?, mtime=? WHERE path=?",
                    (entry.sha256, entry.size, entry.mtime, entry.path),
                )
            return False

        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO files "
                "(path, sha256, size, mtime, primary_bucket, subtype, summary, tags, "
                "confidence, user_override, classified_at, classifier_model) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET "
                "sha256=excluded.sha256, size=excluded.size, mtime=excluded.mtime, "
                "primary_bucket=excluded.primary_bucket, subtype=excluded.subtype, "
                "summary=excluded.summary, tags=excluded.tags, "
                "confidence=excluded.confidence, classified_at=excluded.classified_at, "
                "classifier_model=excluded.classifier_model",
                (
                    entry.path,
                    entry.sha256,
                    entry.size,
                    entry.mtime,
                    entry.primary_bucket,
                    entry.subtype,
                    entry.summary,
                    json.dumps(entry.tags, ensure_ascii=False),
                    entry.confidence,
                    1 if entry.user_override else 0,
                    entry.classified_at,
                    entry.classifier_model,
                ),
            )
        return True

    def get_file(self, path: str) -> FileEntry | None:
        with self.cursor() as cur:
            cur.execute(
                "SELECT path, sha256, size, mtime, primary_bucket, subtype, summary, "
                "tags, confidence, user_override, classified_at, classifier_model "
                "FROM files WHERE path = ?",
                (path,),
            )
            row = cur.fetchone()
        return _row_to_entry(row) if row else None

    def list_by_bucket(
        self,
        bucket: str | None = None,
        *,
        subtype: str | None = None,
        limit: int = 200,
    ) -> list[FileEntry]:
        clauses: list[str] = []
        params: list = []
        if bucket is not None:
            clauses.append("primary_bucket = ?")
            params.append(bucket)
        if subtype is not None:
            clauses.append("subtype = ?")
            params.append(subtype)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        with self.cursor() as cur:
            cur.execute(
                f"SELECT path, sha256, size, mtime, primary_bucket, subtype, summary, "
                f"tags, confidence, user_override, classified_at, classifier_model "
                f"FROM files {where} ORDER BY mtime DESC LIMIT ?",
                params,
            )
            rows = cur.fetchall()
        return [_row_to_entry(r) for r in rows]

    def set_user_override(
        self,
        path: str,
        primary_bucket: str,
        subtype: str | None = None,
        tags: list[str] | None = None,
    ) -> bool:
        """用户手动校正——后续 LLM 分类不会再覆盖该行。"""
        if primary_bucket not in PRIMARY_BUCKETS:
            raise ValueError(f"invalid primary_bucket: {primary_bucket!r}")
        with self.cursor() as cur:
            cur.execute(
                "UPDATE files SET primary_bucket=?, subtype=?, tags=?, "
                "user_override=1, classified_at=? WHERE path=?",
                (
                    primary_bucket,
                    subtype,
                    json.dumps(list(tags or []), ensure_ascii=False),
                    int(time.time()),
                    path,
                ),
            )
            return cur.rowcount > 0

    def stats(self) -> ClassificationStats:
        with self.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM files")
            total = cur.fetchone()["n"]
            cur.execute(
                "SELECT primary_bucket, COUNT(*) AS n FROM files GROUP BY primary_bucket"
            )
            by_bucket = {row["primary_bucket"]: row["n"] for row in cur.fetchall()}
            cur.execute("SELECT MAX(classified_at) AS m FROM files")
            last = cur.fetchone()["m"]
            cur.execute("SELECT COUNT(*) AS n FROM files WHERE user_override = 1")
            override_count = cur.fetchone()["n"]
        for bucket in PRIMARY_BUCKETS:
            by_bucket.setdefault(bucket, 0)
        return ClassificationStats(
            total=total,
            by_bucket=by_bucket,
            last_classified_at=last,
            user_override_count=override_count,
        )

    def delete_file(self, path: str) -> bool:
        with self.cursor() as cur:
            cur.execute("DELETE FROM files WHERE path = ?", (path,))
            return cur.rowcount > 0


def _row_to_entry(row: sqlite3.Row) -> FileEntry:
    tags_raw = row["tags"]
    try:
        tags = json.loads(tags_raw) if tags_raw else []
    except json.JSONDecodeError:
        tags = []
    return FileEntry(
        path=row["path"],
        sha256=row["sha256"],
        size=row["size"],
        mtime=row["mtime"],
        primary_bucket=row["primary_bucket"],
        subtype=row["subtype"],
        summary=row["summary"],
        tags=tags,
        confidence=row["confidence"] or 0.0,
        user_override=bool(row["user_override"]),
        classified_at=row["classified_at"],
        classifier_model=row["classifier_model"],
    )


# ---------------------------------------------------------------------------
# 进程级 db 工厂：按 project_path 缓存
# ---------------------------------------------------------------------------

_db_cache: dict[str, ClassificationDb] = {}
_cache_lock = threading.Lock()


def get_db_for_project(project_path: str | Path) -> ClassificationDb:
    key = str(Path(project_path).resolve())
    with _cache_lock:
        db = _db_cache.get(key)
        if db is None:
            db = ClassificationDb(key)
            _db_cache[key] = db
        return db


def reset_db_cache() -> None:
    """测试 helper：清空缓存并 close 所有连接。"""
    with _cache_lock:
        for db in _db_cache.values():
            db.close()
        _db_cache.clear()
