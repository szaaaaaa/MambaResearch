"""Workspace 扫描器测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.server.workspace.classification import (
    ClassificationDb,
    PRIMARY_BUCKETS,
    reset_db_cache,
)
from src.server.workspace.scanner import (
    SKIPPED_LARGE_SHA,
    scan_source_dir,
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


def _mkfile(p: Path, content: bytes = b"hello") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def test_scan_new_files_marked_unknown(db: ClassificationDb, tmp_path: Path) -> None:
    src = tmp_path / "src"
    _mkfile(src / "a.py")
    _mkfile(src / "b.txt")
    result = scan_source_dir(db, src)
    assert result.scanned == 2
    assert result.new == 2
    assert result.unchanged == 0
    a = db.get_file(str((src / "a.py").resolve()))
    assert a is not None
    assert a.primary_bucket == "unknown"
    assert a.sha256 != ""


def test_scan_skips_blacklisted_dirs(db: ClassificationDb, tmp_path: Path) -> None:
    src = tmp_path / "src"
    _mkfile(src / "code.py")
    _mkfile(src / "node_modules" / "lib.js")
    _mkfile(src / ".git" / "HEAD")
    _mkfile(src / "subdir" / ".venv" / "x.py")
    result = scan_source_dir(db, src)
    assert result.scanned == 1  # 只有 code.py
    assert any("node_modules" in d for d in result.skipped_dirs)


def test_scan_increment_unchanged(db: ClassificationDb, tmp_path: Path) -> None:
    src = tmp_path / "src"
    _mkfile(src / "a.py", content=b"v1")
    scan_source_dir(db, src)
    # 第二次 scan 应识别为 unchanged
    r2 = scan_source_dir(db, src)
    assert r2.unchanged == 1
    assert r2.new == 0


def test_scan_detects_change(db: ClassificationDb, tmp_path: Path) -> None:
    import os
    import time

    src = tmp_path / "src"
    f = _mkfile(src / "a.py", content=b"v1")
    scan_source_dir(db, src)
    # 改内容后再 touch 改 mtime（write_bytes 会重置 mtime，所以顺序很重要）
    f.write_bytes(b"v2")
    new_mtime = int(time.time()) + 10
    os.utime(f, (new_mtime, new_mtime))
    r2 = scan_source_dir(db, src)
    assert r2.changed == 1
    a = db.get_file(str(f.resolve()))
    assert a.size == 2


def test_large_file_gets_placeholder_sha(db: ClassificationDb, tmp_path: Path, monkeypatch) -> None:
    """模拟大文件场景——把阈值改小。"""
    from src.server.workspace import scanner

    monkeypatch.setattr(scanner, "MAX_HASH_SIZE_BYTES", 4)
    src = tmp_path / "src"
    _mkfile(src / "big.bin", content=b"hello world")  # 11 bytes > 4
    result = scan_source_dir(db, src)
    assert result.scanned == 1
    assert result.skipped_large == 1
    f = db.get_file(str((src / "big.bin").resolve()))
    assert f is not None
    assert f.sha256 == SKIPPED_LARGE_SHA


def test_max_files_truncates(db: ClassificationDb, tmp_path: Path) -> None:
    src = tmp_path / "src"
    for i in range(10):
        _mkfile(src / f"f{i}.txt", content=f"v{i}".encode())
    result = scan_source_dir(db, src, max_files=3)
    assert result.scanned == 3
    assert result.truncated is True


def test_user_override_preserved_through_scan(
    db: ClassificationDb, tmp_path: Path
) -> None:
    src = tmp_path / "src"
    f = _mkfile(src / "paper.pdf", content=b"v1")
    scan_source_dir(db, src)
    # 用户校正
    p = str(f.resolve())
    db.set_user_override(p, "literature", subtype="paper_pdf")
    # 文件改动后再扫描——分类不应被覆盖回 unknown
    import os
    import time

    f.write_bytes(b"v2")
    new_mtime = int(time.time()) + 10
    os.utime(f, (new_mtime, new_mtime))
    scan_source_dir(db, src)
    e = db.get_file(p)
    assert e.primary_bucket == "literature"
    assert e.user_override is True
