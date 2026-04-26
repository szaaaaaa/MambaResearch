"""Workbench cwd 绑定 + active project env 注入测试。

覆盖：
- ``activate_project`` 触发 ``MAMBA_ACTIVE_PROJECT_PATH`` env 设置
- ``delete_project`` 清空 env（当被删的是 active 时）
- ``_resolve_cwd`` 默认 active project + 越界拒绝
- 普通会话路由在无 active project 时返 409
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.projects.registry import (
    ACTIVE_PROJECT_ENV_VAR,
    ProjectRegistry,
    set_registry_for_tests,
    sync_active_project_env,
)
from src.server.routes.claude_code import (
    _require_active_project_for_session,
    _resolve_cwd,
)
from src.server.routes.codex import _resolve_cwd as codex_resolve_cwd


@pytest.fixture
def temp_registry(tmp_path: Path):
    registry = ProjectRegistry(registry_path=tmp_path / "reg.json")
    set_registry_for_tests(registry)
    # 测试隔离：清理任何残留 env
    os.environ.pop(ACTIVE_PROJECT_ENV_VAR, None)
    yield registry
    set_registry_for_tests(None)
    os.environ.pop(ACTIVE_PROJECT_ENV_VAR, None)


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    p.mkdir()
    return p


def test_activate_sets_env(temp_registry, project_dir: Path) -> None:
    project = temp_registry.create_project(name="x", path=str(project_dir))
    assert ACTIVE_PROJECT_ENV_VAR not in os.environ
    temp_registry.activate_project(project.id)
    assert os.environ[ACTIVE_PROJECT_ENV_VAR] == str(project_dir.resolve())


def test_delete_active_clears_env(temp_registry, project_dir: Path) -> None:
    project = temp_registry.create_project(name="x", path=str(project_dir))
    temp_registry.activate_project(project.id)
    assert ACTIVE_PROJECT_ENV_VAR in os.environ
    temp_registry.delete_project(project.id)
    assert ACTIVE_PROJECT_ENV_VAR not in os.environ


def test_delete_non_active_does_not_clear_env(
    temp_registry, project_dir: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    p1 = temp_registry.create_project(name="x", path=str(project_dir))
    p2 = temp_registry.create_project(name="y", path=str(other))
    temp_registry.activate_project(p1.id)
    temp_registry.delete_project(p2.id)
    assert os.environ[ACTIVE_PROJECT_ENV_VAR] == str(project_dir.resolve())


def test_sync_env_reads_active(temp_registry, project_dir: Path) -> None:
    project = temp_registry.create_project(name="x", path=str(project_dir))
    temp_registry.activate_project(project.id)
    os.environ.pop(ACTIVE_PROJECT_ENV_VAR, None)
    sync_active_project_env()
    assert os.environ[ACTIVE_PROJECT_ENV_VAR] == str(project_dir.resolve())


def test_resolve_cwd_defaults_to_active_project(
    temp_registry, project_dir: Path
) -> None:
    project = temp_registry.create_project(name="x", path=str(project_dir))
    temp_registry.activate_project(project.id)
    cwd = _resolve_cwd(None)
    assert Path(cwd) == project_dir.resolve()
    cwd_codex = codex_resolve_cwd(None)
    assert Path(cwd_codex) == project_dir.resolve()


def test_resolve_cwd_subdirectory_allowed(
    temp_registry, project_dir: Path
) -> None:
    project = temp_registry.create_project(name="x", path=str(project_dir))
    temp_registry.activate_project(project.id)
    sub = project_dir / "sub"
    sub.mkdir()
    cwd = _resolve_cwd(str(sub))
    assert Path(cwd) == sub.resolve()


def test_resolve_cwd_outside_active_rejected(
    temp_registry, project_dir: Path, tmp_path: Path
) -> None:
    from fastapi import HTTPException

    project = temp_registry.create_project(name="x", path=str(project_dir))
    temp_registry.activate_project(project.id)
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(HTTPException) as exc:
        _resolve_cwd(str(outside))
    assert exc.value.status_code == 400


def test_require_active_project_raises_when_none(temp_registry) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _require_active_project_for_session()
    assert exc.value.status_code == 409


def test_require_active_project_passes_when_active(
    temp_registry, project_dir: Path
) -> None:
    project = temp_registry.create_project(name="x", path=str(project_dir))
    temp_registry.activate_project(project.id)
    # 不应抛
    _require_active_project_for_session()
