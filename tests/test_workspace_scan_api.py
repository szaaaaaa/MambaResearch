"""Workspace scan / stats / files / override API 路由测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.projects.registry import (
    ProjectRegistry,
    set_registry_for_tests,
)
from src.server.projects.workspace import add_source_dir
from src.server.routes.workspace import router as workspace_router
from src.server.workspace.classification import reset_db_cache


@pytest.fixture
def app(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_bytes(b"v1")
    (src / "b.txt").write_bytes(b"hello")
    registry = ProjectRegistry(registry_path=tmp_path / "reg.json")
    set_registry_for_tests(registry)
    project = registry.create_project(name="p", path=str(proj))
    registry.activate_project(project.id)
    add_source_dir(project.path, str(src))

    app = FastAPI()
    app.include_router(workspace_router)
    yield app, src
    set_registry_for_tests(None)
    reset_db_cache()


def test_scan_returns_counts(app) -> None:
    a, src = app
    client = TestClient(a)
    resp = client.post("/api/workspace/scan", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] == 2
    assert body["new"] == 2


def test_scan_with_explicit_source_dir(app) -> None:
    a, src = app
    client = TestClient(a)
    resp = client.post("/api/workspace/scan", json={"source_dir": str(src)})
    assert resp.status_code == 200
    assert resp.json()["scanned"] == 2


def test_scan_no_sources_returns_400(app, tmp_path: Path) -> None:
    a, src = app
    # 删掉所有源目录
    from src.server.projects.workspace import remove_source_dir, load_workspace

    cfg = load_workspace(str(tmp_path / "proj"))
    for d in list(cfg.source_dirs):
        remove_source_dir(str(tmp_path / "proj"), d)

    client = TestClient(a)
    resp = client.post("/api/workspace/scan", json={})
    assert resp.status_code == 400


def test_stats_after_scan(app) -> None:
    a, src = app
    client = TestClient(a)
    client.post("/api/workspace/scan", json={})
    stats = client.get("/api/workspace/stats")
    assert stats.status_code == 200
    body = stats.json()
    assert body["total"] == 2
    assert body["by_bucket"]["unknown"] == 2


def test_list_files_filters_bucket(app) -> None:
    a, src = app
    client = TestClient(a)
    client.post("/api/workspace/scan", json={})
    files = client.get("/api/workspace/files", params={"bucket": "unknown"})
    assert files.status_code == 200
    assert len(files.json()["files"]) == 2


def test_list_files_invalid_bucket(app) -> None:
    a, src = app
    client = TestClient(a)
    resp = client.get("/api/workspace/files", params={"bucket": "nonsense"})
    assert resp.status_code == 400


def test_override_changes_bucket(app) -> None:
    a, src = app
    client = TestClient(a)
    client.post("/api/workspace/scan", json={})
    file_path = str((src / "a.py").resolve())
    resp = client.post(
        "/api/workspace/files/override",
        json={"path": file_path, "primary_bucket": "experiment", "subtype": "train_script"},
    )
    assert resp.status_code == 200, resp.text
    files = client.get("/api/workspace/files", params={"bucket": "experiment"}).json()
    assert any(f["path"] == file_path for f in files["files"])


def test_override_unknown_path_404(app) -> None:
    a, src = app
    client = TestClient(a)
    resp = client.post(
        "/api/workspace/files/override",
        json={"path": "/never/here", "primary_bucket": "literature"},
    )
    assert resp.status_code == 404
