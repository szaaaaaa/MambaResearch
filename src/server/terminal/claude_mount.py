"""为 PTY ``claude`` 准备 ``--add-dir`` 投递目录。

为什么需要这个目录
------------------
Claude Code CLI 通过 ``--add-dir <dir>`` 加额外目录后，会自动从
``<dir>/.claude/skills/`` 加载 skill（参见官方文档 "Skills from additional
directories"）。我们想让 mamba 8 个 pipeline skill（住在
``<repo>/.skills-shared/``）能被 spawn 在 active project cwd 下的 ``claude``
子进程发现，但又不想把整个 ``D:\\ResearchAgent`` 都暴露给该子进程的工具
访问域。

方案
----
建一个最小 mount 目录 ``<repo>/.claude-mount/.claude/skills/<name>``，每个
``<name>`` 是同卷 NTFS junction 指回 ``<repo>/.skills-shared/<name>``。
PTY spawn 时 ``--add-dir <repo>/.claude-mount`` ——Claude 工具只能看到这个
目录及其内的 skill junction，不会触到 mamba 源码。

幂等：每次 PTY spawn 时调用，已存在 junction 跳过、缺则补。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_MOUNT_SUBDIR = ".claude-mount"
_SHARED_SUBDIR = ".skills-shared"

# Windows 文件属性位：reparse point（NTFS junction / symlink）
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _is_reparse_point(path: Path) -> bool:
    """判断 path 是否为 NTFS reparse point（junction 或 symlink）。

    ``Path.is_symlink()`` 在 Windows 上不识别 junction，必须看
    ``stat.st_file_attributes``。
    """
    try:
        st = path.lstat()
    except OSError:
        return False
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


def _make_junction(link: Path, target: Path) -> bool:
    """用 ``mklink /J`` 建 NTFS junction。同卷必成；跨卷会失败。"""
    try:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        logger.exception("mklink subprocess failed: %s -> %s", link, target)
        return False
    if result.returncode != 0:
        logger.warning(
            "mklink failed: %s -> %s; stderr=%s",
            link,
            target,
            result.stderr.strip(),
        )
        return False
    return True


def ensure_claude_mount(repo_root: Path) -> Path | None:
    """确保 ``<repo>/.claude-mount/.claude/skills/`` 下每个 skill 都是 junction
    指回 ``<repo>/.skills-shared/<name>``。

    Parameters
    ----------
    repo_root : Path
        ResearchAgent 仓根目录。``<repo>/.skills-shared/`` 必须存在，否则
        本函数无事可做。

    Returns
    -------
    Path | None
        成功（mount 目录已就绪）时返回 ``<repo>/.claude-mount`` 绝对路径；
        ``.skills-shared`` 不存在 / mkdir 失败时返回 ``None``，调用方应据此
        跳过 ``--add-dir`` flag。
    """
    shared = repo_root / _SHARED_SUBDIR
    if not shared.is_dir():
        logger.warning(
            "ensure_claude_mount: %s does not exist; skipping mount setup",
            shared,
        )
        return None

    mount_root = repo_root / _MOUNT_SUBDIR
    skills_dir = mount_root / ".claude" / "skills"
    try:
        skills_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "ensure_claude_mount: failed to mkdir %s: %s; skipping mount",
            skills_dir,
            exc,
        )
        return None

    for skill_dir in shared.iterdir():
        if not skill_dir.is_dir():
            continue
        link = skills_dir / skill_dir.name
        if link.exists() or _is_reparse_point(link):
            if _is_reparse_point(link):
                continue
            # 真目录占位——不做 risk-of-data-loss 删除，跳过让用户手动清理
            logger.warning(
                "ensure_claude_mount: %s exists but is not a junction; skipping",
                link,
            )
            continue
        _make_junction(link, skill_dir)

    return mount_root


__all__ = ["ensure_claude_mount"]
