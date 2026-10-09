"""Workspace 配置：项目内的 ``source_dirs`` 列表。

每个 project 在自己的 ``<path>/.mambaresearch/workspace.json`` 中记录用户配置
的源目录列表（即"工作区视野"——MambaResearch 看哪些目录里的文件）。

Stage 1 范围
~~~~~~~~~~~~
仅 ``source_dirs`` 字段的 CRUD。Stage 2 引入分类索引时另起 ``classification.db``，
不混进 ``workspace.json``。
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


_WORKSPACE_FILENAME = "workspace.json"
_META_DIR = ".mambaresearch"


class WorkspaceError(Exception):
    """Workspace 模块基类。"""


class WorkspacePathError(WorkspaceError):
    """传入路径校验失败。"""


@dataclass
class WorkspaceConfig:
    """项目级 workspace 配置。"""

    source_dirs: list[str] = field(default_factory=list)
    created_at: int = 0

    def to_dict(self) -> dict:
        return {"source_dirs": list(self.source_dirs), "created_at": self.created_at}

    @classmethod
    def from_dict(cls, raw: dict) -> "WorkspaceConfig":
        dirs_raw = raw.get("source_dirs") or []
        if not isinstance(dirs_raw, list):
            raise WorkspaceError("source_dirs 必须是列表")
        return cls(
            source_dirs=[str(p) for p in dirs_raw],
            created_at=int(raw.get("created_at") or 0),
        )


_locks: dict[str, threading.Lock] = {}
_lock_registry_lock = threading.Lock()


def _lock_for(project_path: str) -> threading.Lock:
    """每个 project_path 一把锁，避免不同项目互相阻塞。"""
    with _lock_registry_lock:
        lock = _locks.get(project_path)
        if lock is None:
            lock = threading.Lock()
            _locks[project_path] = lock
        return lock


def _workspace_file(project_path: str) -> Path:
    return Path(project_path) / _META_DIR / _WORKSPACE_FILENAME


def load_workspace(project_path: str) -> WorkspaceConfig:
    """读取项目的 workspace 配置；不存在 → 返回空配置（不写盘）。"""
    file = _workspace_file(project_path)
    if not file.exists():
        return WorkspaceConfig()
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"workspace.json 损坏 {file}: {exc}") from exc
    return WorkspaceConfig.from_dict(raw)


def save_workspace(project_path: str, config: WorkspaceConfig) -> None:
    """原子写入 workspace 配置。"""
    file = _workspace_file(project_path)
    file.parent.mkdir(parents=True, exist_ok=True)
    if config.created_at == 0:
        config.created_at = int(time.time())
    tmp = file.with_suffix(file.suffix + ".tmp")
    tmp.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, file)


def add_source_dir(project_path: str, source_dir: str) -> WorkspaceConfig:
    """加一个源目录；路径必须存在且是目录；重复加抛 ``WorkspacePathError``。"""
    normalized = _normalize_existing_dir(source_dir)
    with _lock_for(project_path):
        config = load_workspace(project_path)
        if normalized in config.source_dirs:
            raise WorkspacePathError(f"源目录已存在: {normalized}")
        config.source_dirs.append(normalized)
        save_workspace(project_path, config)
        return config


def remove_source_dir(project_path: str, source_dir: str) -> WorkspaceConfig:
    """删源目录；不存在抛 ``WorkspacePathError``。"""
    # 删除允许传入未规范化路径——尝试先匹配 raw 再尝试规范化
    target_candidates = {source_dir}
    try:
        target_candidates.add(_normalize_existing_dir(source_dir))
    except WorkspacePathError:
        # 用户可能在源目录被外部删除后才请求移除——允许只用字符串匹配
        pass
    try:
        target_candidates.add(str(Path(os.path.expanduser(source_dir)).resolve(strict=False)))
    except OSError:
        pass

    with _lock_for(project_path):
        config = load_workspace(project_path)
        new_dirs = [d for d in config.source_dirs if d not in target_candidates]
        if len(new_dirs) == len(config.source_dirs):
            raise WorkspacePathError(f"源目录未注册: {source_dir}")
        config.source_dirs = new_dirs
        save_workspace(project_path, config)
        return config


def _normalize_existing_dir(path: str) -> str:
    try:
        resolved = Path(os.path.expanduser(path)).resolve(strict=False)
    except OSError as exc:
        raise WorkspacePathError(f"无法解析路径 {path}: {exc}") from exc
    if not resolved.exists():
        raise WorkspacePathError(f"路径不存在: {resolved}")
    if not resolved.is_dir():
        raise WorkspacePathError(f"路径不是目录: {resolved}")
    return str(resolved)
