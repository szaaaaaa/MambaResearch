"""research_dag MCP 包装层测试。

本文件随 Stage 5 Task 1 (a/b/c) 增长：
- 1a: ``runtime_holder`` 单例缓存
- 1b: 5 个粗粒度工具
- 1c: 21 个细粒度 skill 工具
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.dynamic_os.runtime import DynamicResearchRuntime
from src.server.integrations.research_dag.runtime_holder import (
    close_runtime,
    get_runtime,
    get_runtime_for_active_project,
    reset_holder_for_tests,
)
from src.server.projects.registry import (
    ProjectRegistry,
    set_registry_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_runtime_holder():
    """每个测试前后都清空 holder 缓存，避免跨测试串味。"""
    reset_holder_for_tests()
    yield
    reset_holder_for_tests()


# ---------------------------------------------------------------------------
# get_runtime — 单例缓存
# ---------------------------------------------------------------------------


def test_get_runtime_returns_singleton_for_same_root(tmp_path: Path):
    rt1 = get_runtime(tmp_path)
    rt2 = get_runtime(tmp_path)
    assert rt1 is rt2
    assert isinstance(rt1, DynamicResearchRuntime)


def test_get_runtime_different_roots_get_different_instances(
    tmp_path_factory: pytest.TempPathFactory,
):
    a = tmp_path_factory.mktemp("proj_a")
    b = tmp_path_factory.mktemp("proj_b")
    rt_a = get_runtime(a)
    rt_b = get_runtime(b)
    assert rt_a is not rt_b


def test_get_runtime_normalizes_str_and_path_to_same_key(tmp_path: Path):
    """传 ``str`` 与 ``Path`` 因 ``Path.resolve()`` 归一化，应拿同一实例。"""
    rt1 = get_runtime(str(tmp_path))
    rt2 = get_runtime(Path(tmp_path))
    assert rt1 is rt2


# ---------------------------------------------------------------------------
# close_runtime
# ---------------------------------------------------------------------------


def test_close_runtime_drops_cache_so_next_get_creates_new(tmp_path: Path):
    rt1 = get_runtime(tmp_path)
    close_runtime(tmp_path)
    rt2 = get_runtime(tmp_path)
    assert rt1 is not rt2


def test_close_runtime_unknown_root_is_noop(tmp_path: Path):
    """未建过的 root 调用 close 不应抛。"""
    close_runtime(tmp_path)
    close_runtime(tmp_path / "nonexistent")


# ---------------------------------------------------------------------------
# reset_holder_for_tests
# ---------------------------------------------------------------------------


def test_reset_holder_clears_all_entries(tmp_path_factory: pytest.TempPathFactory):
    a = tmp_path_factory.mktemp("proj_a")
    b = tmp_path_factory.mktemp("proj_b")
    rt_a1 = get_runtime(a)
    rt_b1 = get_runtime(b)
    reset_holder_for_tests()
    rt_a2 = get_runtime(a)
    rt_b2 = get_runtime(b)
    assert rt_a1 is not rt_a2
    assert rt_b1 is not rt_b2


# ---------------------------------------------------------------------------
# get_runtime_for_active_project
# ---------------------------------------------------------------------------


def test_get_runtime_for_active_project_returns_runtime_when_active():
    """conftest autouse fixture 已设了 active project，应直接拿到 runtime。"""
    rt = get_runtime_for_active_project()
    assert rt is not None
    assert isinstance(rt, DynamicResearchRuntime)


def test_get_runtime_for_active_project_caches_per_active():
    """连续调两次拿同一 runtime（active project 同一）。"""
    rt1 = get_runtime_for_active_project()
    rt2 = get_runtime_for_active_project()
    assert rt1 is rt2


def test_get_runtime_for_active_project_returns_none_when_no_active(
    tmp_path: Path,
):
    """显式覆盖 conftest registry，模拟"无 active project"的状态。"""
    empty_registry_path = tmp_path / "empty_projects.json"
    empty = ProjectRegistry(registry_path=empty_registry_path)
    set_registry_for_tests(empty)
    assert get_runtime_for_active_project() is None


def test_get_runtime_switches_when_active_project_changes(
    tmp_path_factory: pytest.TempPathFactory,
):
    """切到不同 active project → 拿到不同 runtime 实例。"""
    proj_a = tmp_path_factory.mktemp("active_proj_a")
    proj_b = tmp_path_factory.mktemp("active_proj_b")
    registry_path = tmp_path_factory.mktemp("switch_registry") / "projects.json"
    registry = ProjectRegistry(registry_path=registry_path)
    set_registry_for_tests(registry)
    p_a = registry.create_project(name="a", path=str(proj_a))
    p_b = registry.create_project(name="b", path=str(proj_b))

    registry.activate_project(p_a.id)
    rt_a = get_runtime_for_active_project()
    registry.activate_project(p_b.id)
    rt_b = get_runtime_for_active_project()

    assert rt_a is not None and rt_b is not None
    assert rt_a is not rt_b
