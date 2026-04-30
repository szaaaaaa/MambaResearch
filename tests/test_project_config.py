"""Per-project 配置层测试（D+E 重构 task 3）。

覆盖 acceptance：

1. 切到无 ``.mambaresearch/config.json`` 的项目：``GET /api/project-config``
   返回空 dict，**且不创建文件**
2. ``PATCH`` 后 ``<project>/.mambaresearch/config.json`` 出现且只含写入字段
3. 切到另一项目，前一项目的设置不漏给当前项目
4. ``write_active_project_config`` 拒绝 schema 之外的字段
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
from src.server.projects.registry import (
    PROJECT_CONFIG_FILE,
    PROJECT_META_DIR,
    ProjectError,
    ProjectRegistry,
    active_project_config,
    set_registry_for_tests,
    write_active_project_config,
)


@pytest.fixture
def isolated_two_projects(tmp_path_factory: pytest.TempPathFactory):
    """构造两个隔离的项目，初始 active 为 project A。返回 (registry, A_path, B_path, A_id, B_id)。"""
    a_path = tmp_path_factory.mktemp("project_a")
    b_path = tmp_path_factory.mktemp("project_b")
    registry_path = tmp_path_factory.mktemp("registry") / "projects.json"
    registry = ProjectRegistry(registry_path=registry_path)
    set_registry_for_tests(registry)

    a = registry.create_project(name="A", path=str(a_path))
    b = registry.create_project(name="B", path=str(b_path))
    registry.activate_project(a.id)
    try:
        yield registry, a_path, b_path, a.id, b.id
    finally:
        set_registry_for_tests(None)


def _config_path(project_path: Path) -> Path:
    return project_path / PROJECT_META_DIR / PROJECT_CONFIG_FILE


# ---------------------------------------------------------------------------
# AC1: GET 不创建文件
# ---------------------------------------------------------------------------


def test_get_returns_empty_without_creating_file(isolated_two_projects):
    _registry, a_path, _b_path, _a_id, _b_id = isolated_two_projects
    assert not _config_path(a_path).exists()

    cfg = active_project_config()
    assert cfg == {}
    # GET 不能触发文件创建
    assert not _config_path(a_path).exists()


def test_get_route_returns_empty_dict_no_file(isolated_two_projects):
    _registry, a_path, *_ = isolated_two_projects
    client = TestClient(app_module.app)
    resp = client.get("/api/project-config")
    assert resp.status_code == 200
    assert resp.json() == {"config": {}}
    assert not _config_path(a_path).exists()


# ---------------------------------------------------------------------------
# AC2: PATCH 创建文件并只含写入字段
# ---------------------------------------------------------------------------


def test_patch_creates_file_with_only_written_fields(isolated_two_projects):
    _registry, a_path, *_ = isolated_two_projects
    client = TestClient(app_module.app)

    resp = client.patch(
        "/api/project-config",
        json={"enabled_mcp_servers": ["paper_search"]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"config": {"enabled_mcp_servers": ["paper_search"]}}

    cfg_file = _config_path(a_path)
    assert cfg_file.exists()
    import json
    payload = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert payload == {"enabled_mcp_servers": ["paper_search"]}
    assert "codex_profile" not in payload  # 未写的字段不出现


def test_patch_partial_merges_with_existing(isolated_two_projects):
    _registry, _a_path, *_ = isolated_two_projects

    write_active_project_config({"enabled_mcp_servers": ["paper_search"]})
    merged = write_active_project_config({"codex_profile": "personal"})

    assert merged == {
        "enabled_mcp_servers": ["paper_search"],
        "codex_profile": "personal",
    }


# ---------------------------------------------------------------------------
# AC3: 项目隔离
# ---------------------------------------------------------------------------


def test_switching_project_does_not_leak_config(isolated_two_projects):
    registry, a_path, b_path, _a_id, b_id = isolated_two_projects

    # 在 A 项目写一份配置
    write_active_project_config({"codex_profile": "for-A"})
    assert active_project_config() == {"codex_profile": "for-A"}

    # 切到 B 项目
    registry.activate_project(b_id)
    cfg = active_project_config()
    assert cfg == {}, f"B 项目应为空，但读到 {cfg}"
    assert not _config_path(b_path).exists()

    # A 的配置文件仍在原位
    assert _config_path(a_path).exists()


# ---------------------------------------------------------------------------
# AC4: schema 白名单
# ---------------------------------------------------------------------------


def test_unknown_keys_rejected(isolated_two_projects):
    with pytest.raises(ValueError, match="unknown per-project config keys"):
        write_active_project_config({"foo": "bar"})


def test_unknown_keys_via_patch_returns_400(isolated_two_projects):
    client = TestClient(app_module.app)
    resp = client.patch("/api/project-config", json={"foo": "bar"})
    assert resp.status_code == 400
    assert "unknown" in resp.json()["detail"].lower()


def test_command_args_not_in_allowlist(isolated_two_projects):
    """安全边界：command/args 显然不在 schema 里。"""
    with pytest.raises(ValueError):
        write_active_project_config({"command": "/bin/sh"})


# ---------------------------------------------------------------------------
# AC5: 无 active project 时写入抛错
# ---------------------------------------------------------------------------


def test_write_without_active_project_raises(tmp_path_factory: pytest.TempPathFactory):
    registry_path = tmp_path_factory.mktemp("empty_registry") / "projects.json"
    registry = ProjectRegistry(registry_path=registry_path)
    set_registry_for_tests(registry)
    try:
        with pytest.raises(ProjectError, match="no active project"):
            write_active_project_config({"codex_profile": "x"})
    finally:
        set_registry_for_tests(None)
