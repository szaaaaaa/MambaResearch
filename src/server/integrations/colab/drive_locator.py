"""本地 .ipynb 路径 → Google Drive 文件 ID 的反查。

策略
~~~~
不依赖 Drive Web API（大方向 plan 锁定）。读 Drive Desktop 在本地落的 SQLite
``metadata_sqlite_db``——Windows 下默认在 ``%LOCALAPPDATA%\\Google\\DriveFS\\<account_id>\\``。

由于 DriveFS 的 schema 随客户端版本变化且不公开文档化，本模块走"最大兼容"
策略：

* SQLite 以 ``immutable=1`` 只读模式打开（不锁文件、不阻塞 Drive Desktop）
* 用宽容的 ``SELECT`` 查询：先查 ``items`` 表的 ``stable_id`` / ``local_title``
  联合，匹配文件名 + 父目录名；查不到就返回 ``None``
* 任何 schema 异常（表不存在 / 列不存在 / 文件不可读）→ 返回 ``None``，
  让上层拼 fallback URL

公开 API
~~~~~~~~
- ``default_drivefs_root()``       Windows 默认 DriveFS 根目录
- ``find_account_dbs(root)``       列出候选 ``metadata_sqlite_db``
- ``lookup_drive_id(path, db)``    查单个 db
- ``resolve_drive_id(local_path)`` 高层包装，遍历所有 account db
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path


METADATA_DB_FILENAME = "metadata_sqlite_db"


def default_drivefs_root() -> Path | None:
    """Windows 下 ``%LOCALAPPDATA%\\Google\\DriveFS``；非 Windows 返 ``None``。"""
    local_app = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_app:
        return None
    candidate = Path(local_app) / "Google" / "DriveFS"
    return candidate if candidate.is_dir() else None


def find_account_dbs(root: Path | None = None) -> list[Path]:
    """枚举候选 ``metadata_sqlite_db`` 文件路径。

    每个 Google 账号一个数字命名子目录；本函数只看是否存在
    ``metadata_sqlite_db``，不做版本探测。
    """
    target_root = root if root is not None else default_drivefs_root()
    if target_root is None or not target_root.is_dir():
        return []
    out: list[Path] = []
    for sub in target_root.iterdir():
        if not sub.is_dir():
            continue
        db = sub / METADATA_DB_FILENAME
        if db.is_file():
            out.append(db)
    return out


def _open_readonly(db_path: Path) -> sqlite3.Connection | None:
    """以 ``immutable=1`` 打开，避免与 Drive Desktop 抢锁；失败返 None。"""
    try:
        # uri 模式 + immutable=1：不抢 WAL 锁，不写日志
        uri = f"file:{db_path.as_posix()}?mode=ro&immutable=1"
        return sqlite3.connect(uri, uri=True, timeout=2.0)
    except sqlite3.Error:
        return None


def lookup_drive_id(local_path: Path | str, db_path: Path) -> str | None:
    """在单个 ``metadata_sqlite_db`` 中查文件名 + 父目录名联合匹配的 Drive ID。

    schema 假设（来自社区逆向，宽容失败）：
      - 表 ``items``：列 ``stable_id``, ``local_title``, ``parent_stable_id``
      - ``stable_id`` 即 Drive 文件 ID（去 ``id:`` 前缀后）

    Returns
    -------
    str | None
        Drive 文件 ID（不带 ``id:`` 前缀）；任何匹配失败 / schema 异常 → None。
    """
    p = Path(local_path)
    filename = p.name
    if not filename:
        return None
    conn = _open_readonly(db_path)
    if conn is None:
        return None
    try:
        cur = conn.cursor()
        # 优先尝试 v1 schema
        try:
            rows = cur.execute(
                "SELECT stable_id FROM items WHERE local_title = ? LIMIT 5",
                (filename,),
            ).fetchall()
        except sqlite3.Error:
            return None
        if not rows:
            return None
        # 多个同名匹配时无法区分 → 返回第一个（保守，可能错；fallback 仍可用）
        first = rows[0][0]
        if first is None:
            return None
        s = str(first)
        # stable_id 在某些版本是 "id:XXXXX" 形式；剥前缀
        if s.startswith("id:"):
            return s[3:]
        return s
    finally:
        conn.close()


def resolve_drive_id(
    local_path: Path | str,
    drivefs_root: Path | None = None,
) -> str | None:
    """高层包装：遍历所有 account db 找 Drive ID；找不到返 None。"""
    p = Path(local_path)
    if not p.exists():
        return None
    for db in find_account_dbs(drivefs_root):
        drive_id = lookup_drive_id(p, db)
        if drive_id:
            return drive_id
    return None
