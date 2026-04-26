"""测试通用 fixture。

Stage 1 引入 active project 必需性后，旧的 claude_code / codex 测试都假设
"无项目设置就能创建 session"。本 conftest 提供一个 autouse fixture 在每个
测试运行前注入"active project = tmp_path"，让那些不关心项目语义的测试照常工作；
专门测试项目模块的测试通过自己的 fixture 重置 ``set_registry_for_tests``，
对本 fixture 是无感知 override。

**重要**：active project 路径用 ``tmp_path_factory.mktemp`` 而**不是** ``ROOT``——
否则每次跑测试 ``registry._ensure_project_dir`` 会在仓库根创建 ``.mambaresearch/``
污染 ``git status``。
"""

from __future__ import annotations

import pytest

from src.server.projects.registry import (
    ACTIVE_PROJECT_ENV_VAR,
    ProjectRegistry,
    set_registry_for_tests,
)


@pytest.fixture(autouse=True)
def _autouse_default_active_project(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
):
    """对每个测试默认注入 active project=临时目录。

    使用模式：
    - 对不关心项目语义的测试（claude_code / codex 等）：透明生效，session 创建走"有 active project"路径
    - 对显式管理注册表的测试（test_projects_registry / test_workspace_config 等）：
      它们的 fixture 会显式调 ``set_registry_for_tests``，覆盖本 fixture 的状态

    env 清理用 monkeypatch 而非裸 ``os.environ.pop``——pytest 自动恢复，避免
    测试间状态泄漏（包括 ``registry.activate_project`` 内部调用 ``os.environ[...]=``
    设置的值）。
    """
    project_path = tmp_path_factory.mktemp("default_project")
    # 现有 add-dir 等测试假设项目里有 ``src`` 子目录（沿用以前 cwd=repo_ROOT
    # 的默认场景）。conftest mkdir 一份，避免每个测试自己建。
    (project_path / "src").mkdir(exist_ok=True)
    registry_path = tmp_path_factory.mktemp("default_registry") / "projects.json"
    registry = ProjectRegistry(registry_path=registry_path)
    set_registry_for_tests(registry)
    project = registry.create_project(name="default-test-project", path=str(project_path))
    registry.activate_project(project.id)
    # monkeypatch 已 capture 了 activate 内部对 os.environ 的修改；
    # 测试结束自动恢复，无需手动 pop
    monkeypatch.setenv(ACTIVE_PROJECT_ENV_VAR, str(project_path))
    try:
        yield registry
    finally:
        set_registry_for_tests(None)
