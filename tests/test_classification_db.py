"""Classification index 存储层测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.server.workspace.classification import (
    ClassificationDb,
    FileEntry,
    PRIMARY_BUCKETS,
    reset_db_cache,
)


@pytest.fixture
def db(tmp_path: Path) -> ClassificationDb:
    project = tmp_path / "proj"
    project.mkdir()
    instance = ClassificationDb(project)
    instance.connect()
    yield instance
    instance.close()
    reset_db_cache()


def _entry(path: str = "/x/a.py", **overrides) -> FileEntry:
    base = dict(
        path=path,
        sha256="deadbeef",
        size=100,
        mtime=1700000000,
        primary_bucket="experiment",
        subtype="train_script",
        tags=["pytorch"],
    )
    base.update(overrides)
    return FileEntry(**base)


def test_schema_init_creates_tables(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    db = ClassificationDb(project)
    db.connect()
    assert db.db_path.exists()
    # close + reconnect 不抛错
    db.close()
    db.connect()
    db.close()


def test_upsert_inserts_then_updates(db: ClassificationDb) -> None:
    e1 = _entry(summary="initial")
    assert db.upsert_file(e1) is True
    got = db.get_file(e1.path)
    assert got is not None
    assert got.summary == "initial"

    e2 = _entry(summary="updated", primary_bucket="literature", subtype="paper_pdf")
    assert db.upsert_file(e2) is True
    got2 = db.get_file(e1.path)
    assert got2.summary == "updated"
    assert got2.primary_bucket == "literature"


def test_user_override_protected_from_upsert(db: ClassificationDb) -> None:
    e1 = _entry(primary_bucket="experiment")
    db.upsert_file(e1)
    assert db.set_user_override(e1.path, "literature", subtype="paper_pdf") is True

    # 再次 upsert，期望分类字段保留 user 校正
    e2 = _entry(primary_bucket="dataset", summary="LLM 重新分类的", subtype="csv")
    written = db.upsert_file(e2, respect_override=True)
    assert written is False  # 没有覆盖分类
    got = db.get_file(e1.path)
    assert got.primary_bucket == "literature"
    assert got.subtype == "paper_pdf"
    assert got.user_override is True


def test_user_override_can_be_bypassed(db: ClassificationDb) -> None:
    db.upsert_file(_entry())
    db.set_user_override(_entry().path, "literature")
    e2 = _entry(primary_bucket="dataset", summary="bypass test")
    written = db.upsert_file(e2, respect_override=False)
    assert written is True
    got = db.get_file(_entry().path)
    # bypass 模式下 primary_bucket 被强制覆盖；user_override 也被重置
    assert got.primary_bucket == "dataset"


def test_invalid_bucket_rejected(db: ClassificationDb) -> None:
    with pytest.raises(ValueError):
        db.upsert_file(_entry(primary_bucket="nonsense"))


def test_list_by_bucket_filters_and_orders(db: ClassificationDb) -> None:
    db.upsert_file(_entry(path="/p1.py", primary_bucket="experiment", mtime=100))
    db.upsert_file(_entry(path="/p2.pdf", primary_bucket="literature", mtime=200))
    db.upsert_file(_entry(path="/p3.py", primary_bucket="experiment", mtime=300))
    rows = db.list_by_bucket("experiment")
    assert [r.path for r in rows] == ["/p3.py", "/p1.py"]
    rows_lit = db.list_by_bucket("literature")
    assert len(rows_lit) == 1


def test_list_by_subtype(db: ClassificationDb) -> None:
    db.upsert_file(_entry(path="/a.py", subtype="train_script"))
    db.upsert_file(_entry(path="/b.py", subtype="eval_script"))
    rows = db.list_by_bucket("experiment", subtype="train_script")
    assert [r.path for r in rows] == ["/a.py"]


def test_stats(db: ClassificationDb) -> None:
    db.upsert_file(_entry(path="/a.py", primary_bucket="experiment"))
    db.upsert_file(_entry(path="/b.pdf", primary_bucket="literature"))
    db.upsert_file(_entry(path="/c.csv", primary_bucket="dataset"))
    db.upsert_file(_entry(path="/d.md", primary_bucket="idea"))
    stats = db.stats()
    assert stats.total == 4
    assert stats.by_bucket["experiment"] == 1
    assert stats.by_bucket["literature"] == 1
    assert stats.by_bucket["dataset"] == 1
    assert stats.by_bucket["idea"] == 1
    assert stats.by_bucket["unknown"] == 0
    assert stats.last_classified_at is not None


def test_delete_file(db: ClassificationDb) -> None:
    db.upsert_file(_entry(path="/x.py"))
    assert db.delete_file("/x.py") is True
    assert db.get_file("/x.py") is None
    assert db.delete_file("/x.py") is False
