"""Workspace 配置 + routes/workspace.py 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.projects.registry import (
    ProjectRegistry,
    set_registry_for_tests,
)
from src.server.projects.workspace import (
    WorkspacePathError,
    add_source_dir,
    load_workspace,
    remove_source_dir,
)
from src.server.routes.workspace import router as workspace_router


@pytest.fixture
def project(tmp_path: Path):
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    registry = ProjectRegistry(registry_path=tmp_path / "registry.json")
    set_registry_for_tests(registry)
    project = registry.create_project(name="p", path=str(proj_dir))
    registry.activate_project(project.id)
    yield project
    set_registry_for_tests(None)


def test_load_returns_empty_when_missing(project) -> None:
    cfg = load_workspace(project.path)
    assert cfg.source_dirs == []
    assert cfg.created_at == 0


def test_add_source_dir_persists(project, tmp_path: Path) -> None:
    src = tmp_path / "src1"
    src.mkdir()
    cfg = add_source_dir(project.path, str(src))
    assert str(src.resolve()) in cfg.source_dirs

    # 重新加载也能看到
    reloaded = load_workspace(project.path)
    assert str(src.resolve()) in reloaded.source_dirs
    assert reloaded.created_at > 0


def test_add_source_dir_rejects_nonexistent(project) -> None:
    with pytest.raises(WorkspacePathError):
        add_source_dir(project.path, "/definitely/not/here/abc_xyz")


def test_add_source_dir_rejects_file(project, tmp_path: Path) -> None:
    file = tmp_path / "afile.txt"
    file.write_text("hi")
    with pytest.raises(WorkspacePathError):
        add_source_dir(project.path, str(file))


def test_add_source_dir_rejects_duplicate(project, tmp_path: Path) -> None:
    src = tmp_path / "src1"
    src.mkdir()
    add_source_dir(project.path, str(src))
    with pytest.raises(WorkspacePathError):
        add_source_dir(project.path, str(src))


def test_remove_source_dir(project, tmp_path: Path) -> None:
    src = tmp_path / "src1"
    src.mkdir()
    add_source_dir(project.path, str(src))
    cfg = remove_source_dir(project.path, str(src))
    assert cfg.source_dirs == []


def test_remove_source_dir_rejects_unknown(project) -> None:
    with pytest.raises(WorkspacePathError):
        remove_source_dir(project.path, "/never/registered/here")


def test_route_get_returns_409_when_no_active(tmp_path: Path) -> None:
    """无 active project 时 GET /api/workspace 返 409。"""
    registry = ProjectRegistry(registry_path=tmp_path / "registry.json")
    set_registry_for_tests(registry)
    try:
        app = FastAPI()
        app.include_router(workspace_router)
        client = TestClient(app)
        resp = client.get("/api/workspace")
        assert resp.status_code == 409
    finally:
        set_registry_for_tests(None)


def test_route_add_and_get(project, tmp_path: Path) -> None:
    src = tmp_path / "src1"
    src.mkdir()
    app = FastAPI()
    app.include_router(workspace_router)
    client = TestClient(app)

    add = client.post("/api/workspace/source-dirs", json={"path": str(src)})
    assert add.status_code == 200, add.text
    body = add.json()
    assert str(src.resolve()) in body["source_dirs"]

    get = client.get("/api/workspace")
    assert str(src.resolve()) in get.json()["source_dirs"]


def test_route_add_rejects_invalid_path(project) -> None:
    app = FastAPI()
    app.include_router(workspace_router)
    client = TestClient(app)
    resp = client.post("/api/workspace/source-dirs", json={"path": "/never/here"})
    assert resp.status_code == 400


def test_route_add_rejects_duplicate_with_409(project, tmp_path: Path) -> None:
    src = tmp_path / "src1"
    src.mkdir()
    app = FastAPI()
    app.include_router(workspace_router)
    client = TestClient(app)
    client.post("/api/workspace/source-dirs", json={"path": str(src)})
    dup = client.post("/api/workspace/source-dirs", json={"path": str(src)})
    assert dup.status_code == 409


def test_route_remove_unknown_returns_404(project) -> None:
    app = FastAPI()
    app.include_router(workspace_router)
    client = TestClient(app)
    resp = client.request(
        "DELETE", "/api/workspace/source-dirs", json={"path": "/never/here"}
    )
    assert resp.status_code == 404
