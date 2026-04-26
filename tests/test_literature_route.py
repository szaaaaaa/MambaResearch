"""Literature contextual tab 后端路由测试。"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.projects.registry import (
    ProjectRegistry,
    set_registry_for_tests,
)
from src.server.routes.literature import router as literature_router
from src.server.workspace.classification import (
    FileEntry,
    get_db_for_project,
    reset_db_cache,
)


@pytest.fixture
def app_with_proj(tmp_path: Path):
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    (proj_dir / ".mambaresearch").mkdir()
    registry = ProjectRegistry(registry_path=tmp_path / "reg.json")
    set_registry_for_tests(registry)
    project = registry.create_project(name="p", path=str(proj_dir))
    registry.activate_project(project.id)

    app = FastAPI()
    app.include_router(literature_router)
    yield app, proj_dir
    set_registry_for_tests(None)
    reset_db_cache()


def _setup_indexed_file(proj_dir: Path, filename: str, content: bytes) -> Path:
    src_dir = proj_dir / "papers"
    src_dir.mkdir(exist_ok=True)
    file = src_dir / filename
    file.write_bytes(content)
    db = get_db_for_project(proj_dir)
    sha = hashlib.sha256(content).hexdigest()
    db.upsert_file(
        FileEntry(
            path=str(file),
            sha256=sha,
            size=len(content),
            mtime=int(file.stat().st_mtime),
            primary_bucket="literature",
            subtype="paper_pdf",
            summary="Mamba: SSMs with selective scan.",
            tags=["mamba", "ssm"],
            confidence=0.9,
            user_override=False,
            classifier_model="test",
        )
    )
    return file


def test_get_file_returns_pdf_bytes(app_with_proj):
    app, proj_dir = app_with_proj
    pdf = _setup_indexed_file(proj_dir, "paper.pdf", b"%PDF-1.4 fake")
    client = TestClient(app)
    resp = client.get("/api/literature/file", params={"path": str(pdf)})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-1.4 fake"


def test_get_summary_returns_db_metadata(app_with_proj):
    app, proj_dir = app_with_proj
    pdf = _setup_indexed_file(proj_dir, "paper.pdf", b"%PDF-1.4 x")
    client = TestClient(app)
    resp = client.get("/api/literature/summary", params={"path": str(pdf)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["primary_bucket"] == "literature"
    assert body["subtype"] == "paper_pdf"
    assert body["summary"].startswith("Mamba")
    assert body["tags"] == ["mamba", "ssm"]


def test_annotation_roundtrip(app_with_proj):
    app, proj_dir = app_with_proj
    pdf = _setup_indexed_file(proj_dir, "paper.pdf", b"%PDF-1.4 y")
    client = TestClient(app)
    # 默认空
    resp = client.get("/api/literature/annotation", params={"path": str(pdf)})
    assert resp.status_code == 200
    assert resp.text == ""
    # 写入
    resp = client.put(
        "/api/literature/annotation",
        params={"path": str(pdf)},
        content="# 我的标注\n关键观点 X.",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    # 读出来
    resp = client.get("/api/literature/annotation", params={"path": str(pdf)})
    assert resp.status_code == 200
    assert "我的标注" in resp.text


def test_file_returns_404_for_unindexed_path(app_with_proj):
    app, _ = app_with_proj
    client = TestClient(app)
    resp = client.get("/api/literature/file", params={"path": "/nonexistent.pdf"})
    assert resp.status_code == 404


def test_file_returns_409_when_no_active_project(tmp_path):
    """单独跑：没建任何 project + 没 activate 的 registry。"""
    registry = ProjectRegistry(registry_path=tmp_path / "reg.json")
    set_registry_for_tests(registry)
    try:
        app = FastAPI()
        app.include_router(literature_router)
        client = TestClient(app)
        resp = client.get("/api/literature/file", params={"path": "/x.pdf"})
        assert resp.status_code == 409
    finally:
        set_registry_for_tests(None)
        reset_db_cache()
