"""Run timeline 历史路由。

扫 active project 下的 ``outputs/<run_id>/`` 子目录，按 SKILL 命名约定解析
``kind``，从 ``plan.md`` 抽 ``title``，
聚合产出文件名作为 ``artifacts``，统一返回时间倒序的列表。

所有科研流程按统一目录约定读取产物；本模块不读取 Codex 原生聊天或依赖模型执行实现。

run_id 命名约定（来自 CLAUDE.md "Pipeline artifact 命名约定"）::

    lit_review_<YYYYMMDD>_<HHMMSS>             - structured-lit-review
    exp_<YYYYMMDD>_<HHMMSS>                    - empirical-study
    method_cmp_<YYYYMMDD>_<HHMMSS>             - method-comparison
    iter_<YYYYMMDD>_<HHMMSS>                   - experiment-iteration
    review_<YYYYMMDD>_<HHMMSS>_<short_name>    - artifact-review
    brainstorm_<YYYYMMDD>_<HHMMSS>             - idea-brainstorming
    data_explore_<YYYYMMDD>_<HHMMSS>_<short>   - data-exploration

返回字段::

    {
      "run_id":      str,
      "kind":        str,            # one of KIND_VALUES, or "unknown"
      "title":       str,            # 从 plan.md / spec.md 抽，否则 run_id
      "started_at":  int | None,     # 从 run_id 的 YYYYMMDD_HHMMSS 解析
      "artifacts":   list[str],      # 顶层文件名（不含子目录）
    }
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.server.projects.registry import get_registry


router = APIRouter()


# ----------------------------------------------------------------------------
# 命名约定 → kind 的映射
# 顺序敏感：更长的前缀必须在前（"data_explore_" 必须在 "exp_" 之前匹配）
# ----------------------------------------------------------------------------
_KIND_PREFIXES: tuple[tuple[str, str], ...] = (
    ("data_explore_", "data_exploration"),
    ("method_cmp_", "method_comparison"),
    ("lit_review_", "literature_review"),
    ("brainstorm_", "brainstorming"),
    ("review_", "review"),
    ("iter_", "experiment_iteration"),
    ("exp_", "experiment"),
)

# 从 run_id 抽时间戳的正则：第一个 8 位数字 + 下划线 + 6 位数字
_TS_PATTERN = re.compile(r"(\d{8})_(\d{6})")


def _parse_kind(run_id: str) -> str:
    """前缀匹配；不命中返回 "unknown"。"""
    for prefix, kind in _KIND_PREFIXES:
        if run_id.startswith(prefix):
            return kind
    return "unknown"


def _parse_started_at(run_id: str) -> int | None:
    """目录名记录创建主机的本地时间，转换为 unix seconds。"""
    m = _TS_PATTERN.search(run_id)
    if m is None:
        return None
    try:
        dt = datetime.strptime(m.group(0), "%Y%m%d_%H%M%S")
        return int(dt.timestamp())
    except ValueError:
        return None


def _list_top_level_files(run_dir: Path) -> list[str]:
    """run 目录下的顶层文件名（不递归 experiments/ 之类的子目录）。"""
    if not run_dir.is_dir():
        return []
    out: list[str] = []
    for child in run_dir.iterdir():
        if child.is_file():
            out.append(child.name)
    out.sort()
    return out


def _read_title(run_dir: Path, run_id: str) -> str:
    """优先从 plan.md / spec.md / report.md 抽第一行非空文本（去掉 markdown #）。"""
    for candidate in ("plan.md", "spec.md", "report.md"):
        f = run_dir / candidate
        if not f.is_file():
            continue
        try:
            with f.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    # 去掉前导的 markdown heading 标记
                    cleaned = stripped.lstrip("#").strip()
                    if cleaned:
                        # 防止过长 title 把 UI 撑爆
                        return cleaned[:120]
                    return stripped[:120]
        except OSError:
            continue
    return run_id


def _scan_run_dir(run_dir: Path) -> dict | None:
    """扫单个 run 目录，返回结构化记录；目录不可读时返回 None 跳过。"""
    run_id = run_dir.name
    try:
        artifacts = _list_top_level_files(run_dir)
    except OSError:
        return None
    kind = _parse_kind(run_id)
    started_at = _parse_started_at(run_id)
    title = _read_title(run_dir, run_id)
    return {
        "run_id": run_id,
        "kind": kind,
        "title": title,
        "started_at": started_at,
        "artifacts": artifacts,
    }


def scan_outputs_dir(outputs_dir: Path) -> list[dict]:
    """扫指定目录下所有 ``<run_id>/`` 子目录，返回时间倒序列表。

    参数
    ----
    outputs_dir
        ``<project_path>/outputs/`` 这一层。不存在时返回空列表（非错误——
        新项目首次访问就是这种情况）。
    """
    if not outputs_dir.is_dir():
        return []
    runs: list[dict] = []
    for child in outputs_dir.iterdir():
        if not child.is_dir():
            continue
        rec = _scan_run_dir(child)
        if rec is None:
            continue
        runs.append(rec)
    # 按 started_at 倒序；None 排到末尾
    runs.sort(
        key=lambda r: (r["started_at"] is not None, r["started_at"] or 0),
        reverse=True,
    )
    return runs


@router.get("/api/history/runs")
def list_history_runs() -> dict:
    """列 active project 下所有 ``outputs/<run_id>/`` 子目录。

    无 active project → 409。
    """
    project = get_registry().get_active()
    if project is None:
        raise HTTPException(status_code=409, detail="no active project")
    outputs_dir = Path(project.path) / "outputs"
    runs = scan_outputs_dir(outputs_dir)
    return {"runs": runs, "scanned_at": int(time.time())}
