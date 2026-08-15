"""项目注册表。

负责 ``~/.mambaresearch/projects.json`` 的读写和 active project 的管理。

并发模型
--------
注册表实例进程内单例（``get_registry()``），每次写入持有进程内 ``threading.Lock``
做串行；注册表文件独占在本机一个进程，不解决跨进程并发——MambaResearch
后端在本机通常单实例运行，跨进程一致性不在本阶段范围。

文件不存在时 ``load`` 自动初始化空状态而不抛错；首次写入会在 ``mkdir`` 时
创建 ``~/.mambaresearch/`` 目录。

Env 注入
~~~~~~~~
``activate_project`` / ``delete_project`` 会同步更新进程级 env
``MAMBA_ACTIVE_PROJECT_PATH``——这个 env 通过子进程继承传递给后续启动的
MCP server 进程，让它们读到当前 active project 路径。

Per-project 配置（D+E 重构 task 3）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``active_project_config()`` 读 ``<project>/.mambaresearch/config.json``，
``write_active_project_config(updates)`` patch-merge 写。lazy 语义：

- 文件不存在 → 读返回空 dict，**不主动创建**
- 写时若文件不存在才创建；空 updates 不触发写
- 切到没绑定 active project 时读返回空 dict（不抛）；写抛 ``ProjectError``
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from src.server.projects.models import Project, ProjectsState


# 进程级 env 名——MCP server 子进程读它定位 active project
ACTIVE_PROJECT_ENV_VAR = "MAMBA_ACTIVE_PROJECT_PATH"

# 项目本地元数据目录与 per-project 配置文件名
PROJECT_META_DIR = ".mambaresearch"
PROJECT_CONFIG_FILE = "config.json"

# Per-project config 允许的字段——schema 最小集（D+E task 3）。新增字段开新 plan
ALLOWED_PROJECT_CONFIG_KEYS: frozenset[str] = frozenset({
    "enabled_mcp_servers",
})


class ProjectError(Exception):
    """项目模块基类异常。"""


class ProjectNotFoundError(ProjectError):
    """目标 id 在注册表中不存在。"""


class ProjectAlreadyExistsError(ProjectError):
    """同 path 的项目已存在。"""


class ProjectPathError(ProjectError):
    """传入路径不存在 / 不是目录 / 无法解析。"""


_DEFAULT_REGISTRY_DIR = Path.home() / ".mambaresearch"
_DEFAULT_REGISTRY_FILE = _DEFAULT_REGISTRY_DIR / "projects.json"


class ProjectRegistry:
    """项目注册表，封装 ``projects.json`` 的所有访问。

    Parameters
    ----------
    registry_path : Path or None
        注册表文件路径；默认 ``~/.mambaresearch/projects.json``。测试可注入
        临时路径以隔离测试环境。
    """

    def __init__(self, registry_path: Path | None = None) -> None:
        self._path = Path(registry_path) if registry_path else _DEFAULT_REGISTRY_FILE
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    # ---------- IO ----------

    def load(self) -> ProjectsState:
        """从磁盘读取注册表；文件不存在或为空 → 返回空状态。"""
        if not self._path.exists():
            return ProjectsState()
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProjectError(f"无法读取注册表 {self._path}: {exc}") from exc
        if not raw.strip():
            return ProjectsState()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProjectError(f"注册表 JSON 损坏 {self._path}: {exc}") from exc
        return ProjectsState.model_validate(payload)

    def _save(self, state: ProjectsState) -> None:
        """原子覆盖注册表文件——先写到临时文件再 rename，避免半写。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(state.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)

    # ---------- CRUD ----------

    def list_projects(self) -> ProjectsState:
        """返回完整状态（projects + active_project_id）。"""
        return self.load()

    def get_project(self, project_id: str) -> Project:
        state = self.load()
        for project in state.projects:
            if project.id == project_id:
                return project
        raise ProjectNotFoundError(project_id)

    def get_active(self) -> Project | None:
        state = self.load()
        if state.active_project_id is None:
            return None
        for project in state.projects:
            if project.id == state.active_project_id:
                return project
        # 文件被外部修改导致 active_project_id 指向不存在的项目；返回 None 容忍
        return None

    def create_project(self, *, name: str, path: str) -> Project:
        """注册新项目。

        path 必须存在且是目录；否则抛 ``ProjectPathError``。

        **允许同路径重复注册**：同一物理目录可承载多条独立研究线（譬如
        G:\\ 上想跑两条不同主题的研究），各自的项目元数据 / conversations
        / classification.db 在 mambaresearch 侧独立编号，不冲突。物理文件
        自然共享。``ProjectAlreadyExistsError`` 类型保留作 API 兼容，但
        本方法不再抛它。
        """
        normalized_path = self._normalize_path(path)
        with self._lock:
            state = self.load()
            now = int(time.time())
            project = Project(
                id=uuid.uuid4().hex,
                name=name.strip(),
                path=normalized_path,
                created_at=now,
                last_active_at=now,
            )
            state.projects.append(project)
            self._save(state)
            self._ensure_project_dir(normalized_path)
            return project

    def delete_project(self, project_id: str) -> None:
        """从注册表删除项目；若是 active 则 active 清空 + env 清空。

        **不删除物理目录** —— 仅从注册表移除。
        """
        with self._lock:
            state = self.load()
            new_projects = [p for p in state.projects if p.id != project_id]
            if len(new_projects) == len(state.projects):
                raise ProjectNotFoundError(project_id)
            state.projects = new_projects
            cleared_active = state.active_project_id == project_id
            if cleared_active:
                state.active_project_id = None
            self._save(state)
            if cleared_active:
                _apply_active_project_env(None)

    def activate_project(self, project_id: str) -> Project:
        """将项目设为 active，刷新 last_active_at，更新进程 env。"""
        with self._lock:
            state = self.load()
            target: Project | None = None
            for project in state.projects:
                if project.id == project_id:
                    target = project
                    break
            if target is None:
                raise ProjectNotFoundError(project_id)
            target.last_active_at = int(time.time())
            state.active_project_id = project_id
            self._save(state)
            _apply_active_project_env(target.path)
            return target

    # ---------- helpers ----------

    @staticmethod
    def _normalize_path(path: str) -> str:
        """规范化用户传入的项目路径。

        - 展开 ``~``
        - 转绝对路径并解析符号链接
        - 校验存在且为目录
        - 返回 OS 原生分隔符的字符串
        """
        try:
            resolved = Path(os.path.expanduser(path)).resolve(strict=False)
        except OSError as exc:
            raise ProjectPathError(f"无法解析路径 {path}: {exc}") from exc
        if not resolved.exists():
            raise ProjectPathError(f"路径不存在: {resolved}")
        if not resolved.is_dir():
            raise ProjectPathError(f"路径不是目录: {resolved}")
        return str(resolved)

    @staticmethod
    def _ensure_project_dir(project_path: str) -> None:
        """确保项目内的 ``.mambaresearch/`` 目录存在；写一份 .gitignore 以避免误提交分类索引。"""
        meta_dir = Path(project_path) / ".mambaresearch"
        meta_dir.mkdir(parents=True, exist_ok=True)
        gitignore = meta_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(
                "# MambaResearch 项目元数据，不应进入 git\n*\n!.gitignore\n",
                encoding="utf-8",
            )


def _apply_active_project_env(path: str | None) -> None:
    """更新进程级 ``MAMBA_ACTIVE_PROJECT_PATH``。``None`` → 删除该 env。

    MCP server 子进程从父进程继承 env，所以这一步会在后续启动的子进程里生效。
    已运行的子进程感知不到——这是预期行为：active project 切换时通常也要重启
    会话才生效。
    """
    if path is None or not str(path).strip():
        os.environ.pop(ACTIVE_PROJECT_ENV_VAR, None)
        return

    os.environ[ACTIVE_PROJECT_ENV_VAR] = str(path)


def sync_active_project_env() -> None:
    """启动钩子：从当前注册表读 active 并把 env 同步好。"""
    project = get_registry().get_active()
    _apply_active_project_env(project.path if project else None)


# ---------------------------------------------------------------------------
# Per-project config 层（D+E 重构 task 3，lazy 写入）
# ---------------------------------------------------------------------------


def _project_config_path(project_path: str) -> Path:
    return Path(project_path) / PROJECT_META_DIR / PROJECT_CONFIG_FILE


def active_project_config() -> dict:
    """读 active project 的 ``.mambaresearch/config.json``。

    无 active project / 文件不存在 / JSON 损坏 → 返回空 dict。**不创建文件**——
    settings UI GET 端点应永远只返回这个函数的输出而不触发文件写。
    """
    project = get_registry().get_active()
    if project is None:
        return {}
    config_path = _project_config_path(project.path)
    if not config_path.exists():
        return {}
    try:
        with config_path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    # 过滤掉未在 allowlist 中的字段（防止旧字段或 typo 渗入）
    return {k: v for k, v in payload.items() if k in ALLOWED_PROJECT_CONFIG_KEYS}


def write_active_project_config(updates: dict) -> dict:
    """patch-merge 写 active project config，返回写入后的完整字典。

    Parameters
    ----------
    updates : dict
        要写入的字段子集。键必须在 ``ALLOWED_PROJECT_CONFIG_KEYS`` 内，
        不在的字段抛 ``ValueError``——避免 settings UI 误传扩展字段（schema
        扩展走新 plan 流程）。

    Returns
    -------
    dict
        merge 后写入文件的完整 config（仅含 allowlist 字段）。

    Raises
    ------
    ProjectError
        无 active project（无处可写）。
    ValueError
        ``updates`` 含未授权字段。
    """
    if not isinstance(updates, dict):
        raise ValueError("updates must be a dict")
    unknown = set(updates.keys()) - ALLOWED_PROJECT_CONFIG_KEYS
    if unknown:
        raise ValueError(
            f"unknown per-project config keys: {sorted(unknown)}; "
            f"allowed: {sorted(ALLOWED_PROJECT_CONFIG_KEYS)}"
        )

    project = get_registry().get_active()
    if project is None:
        raise ProjectError("no active project — cannot write per-project config")

    existing = active_project_config()
    merged = {**existing, **updates}
    config_path = _project_config_path(project.path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = config_path.with_suffix(config_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, config_path)
    return merged


_REGISTRY_INSTANCE: ProjectRegistry | None = None


def get_registry() -> ProjectRegistry:
    """进程级单例。测试中可通过设置 ``_REGISTRY_INSTANCE`` 注入。"""
    global _REGISTRY_INSTANCE
    if _REGISTRY_INSTANCE is None:
        _REGISTRY_INSTANCE = ProjectRegistry()
    return _REGISTRY_INSTANCE


def set_registry_for_tests(registry: ProjectRegistry | None) -> None:
    """测试 helper：注入或重置注册表单例。生产代码不应调用。"""
    global _REGISTRY_INSTANCE
    _REGISTRY_INSTANCE = registry
    # 测试切换注册表时同步 env，避免测试间状态泄漏
    if registry is None:
        _apply_active_project_env(None)
