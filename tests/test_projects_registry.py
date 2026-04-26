"""Project Registry 与 routes/projects.py 的核心行为测试。

只覆盖：增删改查、active 切换、文件 atomic 写入、并发写、路径校验。
不测：HTTP 401/CORS（不是本模块职责）。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.projects.registry import (
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
    ProjectPathError,
    ProjectRegistry,
    set_registry_for_tests,
)
from src.server.routes.projects import router as projects_router


@pytest.fixture
def temp_registry(tmp_path: Path) -> ProjectRegistry:
    registry_file = tmp_path / "registry" / "projects.json"
    registry = ProjectRegistry(registry_path=registry_file)
    set_registry_for_tests(registry)
    yield registry
    set_registry_for_tests(None)


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    p = tmp_path / "proj_a"
    p.mkdir()
    return p


def test_load_returns_empty_state_when_file_missing(temp_registry: ProjectRegistry) -> None:
    state = temp_registry.list_projects()
    assert state.projects == []
    assert state.active_project_id is None


def test_create_project_persists_to_disk(
    temp_registry: ProjectRegistry, project_dir: Path
) -> None:
    project = temp_registry.create_project(name="my project", path=str(project_dir))
    assert project.name == "my project"
    assert Path(project.path) == project_dir.resolve()
    assert project.id

    # 文件落地、JSON 可读
    raw = json.loads(temp_registry.path.read_text(encoding="utf-8"))
    assert raw["projects"][0]["id"] == project.id
    assert raw["active_project_id"] is None  # registry.create 不自动激活；激活在路由层

    # 项目目录下生成 .mambaresearch 子目录 + .gitignore
    meta_dir = project_dir / ".mambaresearch"
    assert meta_dir.is_dir()
    assert (meta_dir / ".gitignore").exists()


def test_create_project_rejects_nonexistent_path(temp_registry: ProjectRegistry) -> None:
    with pytest.raises(ProjectPathError):
        temp_registry.create_project(name="x", path="/definitely/not/here/xyz_123")


def test_create_project_rejects_file_path(
    temp_registry: ProjectRegistry, tmp_path: Path
) -> None:
    file_path = tmp_path / "not_a_dir.txt"
    file_path.write_text("hello")
    with pytest.raises(ProjectPathError):
        temp_registry.create_project(name="x", path=str(file_path))


def test_create_project_rejects_duplicate_path(
    temp_registry: ProjectRegistry, project_dir: Path
) -> None:
    temp_registry.create_project(name="first", path=str(project_dir))
    with pytest.raises(ProjectAlreadyExistsError):
        temp_registry.create_project(name="second", path=str(project_dir))


def test_activate_and_get_active(
    temp_registry: ProjectRegistry, project_dir: Path
) -> None:
    project = temp_registry.create_project(name="x", path=str(project_dir))
    assert temp_registry.get_active() is None
    activated = temp_registry.activate_project(project.id)
    assert activated.id == project.id
    active = temp_registry.get_active()
    assert active is not None and active.id == project.id


def test_activate_unknown_project_raises(temp_registry: ProjectRegistry) -> None:
    with pytest.raises(ProjectNotFoundError):
        temp_registry.activate_project("nonexistent")


def test_delete_clears_active_when_target_was_active(
    temp_registry: ProjectRegistry, project_dir: Path
) -> None:
    project = temp_registry.create_project(name="x", path=str(project_dir))
    temp_registry.activate_project(project.id)
    temp_registry.delete_project(project.id)
    assert temp_registry.get_active() is None
    assert temp_registry.list_projects().projects == []


def test_delete_unknown_project_raises(temp_registry: ProjectRegistry) -> None:
    with pytest.raises(ProjectNotFoundError):
        temp_registry.delete_project("nonexistent")


def test_concurrent_create_does_not_corrupt(
    temp_registry: ProjectRegistry, tmp_path: Path
) -> None:
    """多线程并发 create 不同路径，最终注册表条目数 == 线程数。"""
    dirs = []
    for i in range(8):
        p = tmp_path / f"proj_{i}"
        p.mkdir()
        dirs.append(p)
    errors: list[Exception] = []

    def worker(d: Path) -> None:
        try:
            temp_registry.create_project(name=d.name, path=str(d))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(d,)) for d in dirs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    state = temp_registry.list_projects()
    assert len(state.projects) == 8
    paths = {p.path for p in state.projects}
    assert len(paths) == 8


def test_route_create_auto_activates(
    temp_registry: ProjectRegistry, project_dir: Path
) -> None:
    """POST /api/projects 创建后立即激活——大方向锁定行为。"""
    app = FastAPI()
    app.include_router(projects_router)
    client = TestClient(app)

    resp = client.post("/api/projects", json={"name": "p", "path": str(project_dir)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    project_id = body["id"]

    active = client.get("/api/projects/active")
    assert active.status_code == 200
    assert active.json()["id"] == project_id


def test_route_active_404_when_none(temp_registry: ProjectRegistry) -> None:
    app = FastAPI()
    app.include_router(projects_router)
    client = TestClient(app)

    resp = client.get("/api/projects/active")
    assert resp.status_code == 404


def test_route_create_rejects_invalid_path(temp_registry: ProjectRegistry) -> None:
    app = FastAPI()
    app.include_router(projects_router)
    client = TestClient(app)

    resp = client.post(
        "/api/projects", json={"name": "x", "path": "/definitely/not/here/xyz_123"}
    )
    assert resp.status_code == 400
    assert "路径" in resp.json()["detail"]


def test_route_delete_returns_status(
    temp_registry: ProjectRegistry, project_dir: Path
) -> None:
    app = FastAPI()
    app.include_router(projects_router)
    client = TestClient(app)

    create = client.post("/api/projects", json={"name": "p", "path": str(project_dir)})
    project_id = create.json()["id"]

    delete = client.delete(f"/api/projects/{project_id}")
    assert delete.status_code == 200
    assert delete.json()["status"] == "deleted"

    # active 已清空
    assert client.get("/api/projects/active").status_code == 404


def test_create_project_with_relative_path_resolves(
    temp_registry: ProjectRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """传入相对路径时，解析到绝对路径。"""
    proj = tmp_path / "rel_proj"
    proj.mkdir()
    monkeypatch.chdir(tmp_path)
    project = temp_registry.create_project(name="r", path="rel_proj")
    assert Path(project.path).is_absolute()
    assert Path(project.path) == proj.resolve()
