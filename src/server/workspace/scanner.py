"""增量文件扫描器——把源目录里"还没认识的"文件入库为 unknown。

设计原则
--------
- **不分类**：分类是 Claude/Codex 通过 LLM + workspace.classify_one MCP 工具完成
  的；scanner 只刷 sha256/mtime/size，并把首次出现的文件标 ``primary_bucket=unknown``
- **增量**：基于 ``mtime`` 比对——已有行且 mtime 没变就不重算 sha256
- **黑名单**：跳过 ``.git`` / ``node_modules`` / venv / 等已知"不该被分类"的目录
- **大文件保护**：> ``MAX_HASH_SIZE_BYTES`` 不计算 sha256，标 ``__skipped_large__``
- **总数上限**：单次 scan 最多 ``MAX_SCAN_FILES`` 个文件，超过返回 ``truncated=True``

返回
~~~~
``ScanResult`` 包含 scanned / new / changed / unchanged / skipped / truncated 计数。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.server.workspace.classification import ClassificationDb, FileEntry


# 跳过的目录名（精确匹配 path.name）
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".env",
        "dist",
        "build",
        ".next",
        "target",
        ".mambaresearch",
        ".pytest_cache",
        ".mypy_cache",
        ".tox",
        ".idea",
        ".vscode",
    }
)

# 单文件 sha256 计算上限（100MB）；超过仍入库但 sha256 标占位
MAX_HASH_SIZE_BYTES = 100 * 1024 * 1024
SKIPPED_LARGE_SHA = "__skipped_large__"

# 单次 scan 最多遍历的文件数（防止极大 workspace 卡死）
MAX_SCAN_FILES = 50_000

# sha256 流式块大小
_HASH_CHUNK = 64 * 1024


@dataclass
class ScanResult:
    scanned: int = 0
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    skipped_large: int = 0
    skipped_dirs: list[str] = field(default_factory=list)
    truncated: bool = False
    duration_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "new": self.new,
            "changed": self.changed,
            "unchanged": self.unchanged,
            "skipped_large": self.skipped_large,
            "skipped_dirs_count": len(self.skipped_dirs),
            "truncated": self.truncated,
            "duration_s": round(self.duration_s, 2),
        }


def scan_source_dir(
    db: ClassificationDb, source_dir: str | Path, *, max_files: int = MAX_SCAN_FILES
) -> ScanResult:
    """扫描单个源目录，把发现的新/改动文件 upsert 到分类索引。

    分类字段保持 ``unknown``——后续 Claude/Codex 调 ``workspace.classify_one`` 完善。
    """
    started = time.time()
    result = ScanResult()
    base = Path(source_dir).resolve()
    if not base.is_dir():
        # 显式抛错——之前静默返 0 让调用方（MCP 工具 / HTTP 路由）以为"扫了
        # 但啥都没找到"，配合 Windows 上 ``Path("/g/...")`` 自动锚到当前盘根
        # 的行为，路径手误会被完全吞掉。改造调用方在 try/except 里把它翻成
        # isError / 400 给上层。
        raise ValueError(
            f"source_dir does not exist or is not a directory (resolved to {base}): "
            f"{source_dir}"
        )

    for entry_path in _iter_files(base, result):
        if result.scanned >= max_files:
            result.truncated = True
            break
        result.scanned += 1
        try:
            stat = entry_path.stat()
        except OSError:
            continue
        size = stat.st_size
        mtime = int(stat.st_mtime)
        path_str = str(entry_path)
        existing = db.get_file(path_str)
        if existing and existing.mtime == mtime and existing.size == size:
            result.unchanged += 1
            continue

        sha = _compute_sha(entry_path, size)
        if sha is None:
            # 文件被删除或权限失败——跳过
            continue
        if sha == SKIPPED_LARGE_SHA:
            result.skipped_large += 1

        new_entry = FileEntry(
            path=path_str,
            sha256=sha,
            size=size,
            mtime=mtime,
            primary_bucket="unknown",
            classified_at=int(time.time()),
        )
        wrote = db.upsert_file(new_entry, respect_override=True)
        if existing is None:
            result.new += 1
        elif wrote:
            result.changed += 1

    result.duration_s = time.time() - started
    return result


def _iter_files(base: Path, result: ScanResult):
    """深度优先遍历 base，跳过黑名单目录。"""
    stack: list[Path] = [base]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        for child in children:
            try:
                if child.is_dir():
                    if child.name in _SKIP_DIRS:
                        result.skipped_dirs.append(str(child))
                        continue
                    stack.append(child)
                elif child.is_file():
                    yield child
                # symlinks / sockets / fifos 忽略
            except OSError:
                continue


def _compute_sha(path: Path, size: int) -> str | None:
    """流式计算 sha256；> MAX 返回占位。读失败返回 None。"""
    if size > MAX_HASH_SIZE_BYTES:
        return SKIPPED_LARGE_SHA
    h = hashlib.sha256()
    try:
        with path.open("rb") as fp:
            while True:
                chunk = fp.read(_HASH_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()
