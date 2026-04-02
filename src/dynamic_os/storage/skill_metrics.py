"""技能指标存储 —— 追踪技能执行表现并计算效用评分。

本模块为 Dynamic Research OS 提供技能级别的运行时指标收集与查询。
每次技能执行结束后，系统调用 ``record_execution`` 记录本次结果，
并通过指数移动平均（EMA）算法实时更新该技能的效用评分（utility_score）。

效用评分用途
-----------
- Planner 在选择技能时参考效用评分，优先调度高效用技能
- 技能进化系统根据效用评分决定是否触发技能改进

评分算法
--------
utility = α × (raw_score × confidence - duration_penalty) + (1 - α) × old_utility

其中:
- raw_score: 由执行状态决定（success=1.0, partial=0.5, failed/skipped=0.0）
- confidence: 执行结果置信度（0~1）
- duration_penalty: 超时惩罚，超过 10 秒开始递增，上限 0.2
- α = 0.3: 新旧权重平衡系数
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Protocol

from src.dynamic_os.contracts.artifact import now_iso as _now_iso


@dataclass(frozen=True)
class SkillMetrics:
    """单个技能的累计运行指标快照（不可变）。

    参数
    ----------
    skill_id : str
        技能唯一标识。
    execution_count : int
        累计执行次数。
    success_count : int
        累计成功次数。
    fail_count : int
        累计失败次数（含 needs_replan）。
    avg_duration_ms : float
        历史平均执行耗时（毫秒），采用在线均值算法更新。
    utility_score : float
        当前效用评分，范围 [0, 1]。
    """

    skill_id: str
    execution_count: int
    success_count: int
    fail_count: int
    avg_duration_ms: float
    utility_score: float


# 新技能的默认效用评分（中等偏好，给予公平尝试机会）
_DEFAULT_UTILITY = 0.5

# EMA 平滑系数：α 越大，新数据点权重越高
_ALPHA = 0.3


def _compute_new_utility(
    old_utility: float,
    status: str,
    confidence: float,
    duration_ms: float,
) -> float:
    """根据本次执行结果计算新的效用评分。

    参数
    ----------
    old_utility : float
        更新前的效用评分。
    status : str
        执行状态：success / partial / failed / needs_replan / skipped。
    confidence : float
        执行结果置信度（0~1）。
    duration_ms : float
        本次执行耗时（毫秒）。

    返回
    -------
    float
        更新后的效用评分，夹紧到 [0, 1]。
    """
    # 各执行状态对应的原始得分
    raw_scores = {"success": 1.0, "partial": 0.5, "failed": 0.0, "needs_replan": 0.0, "skipped": 0.0}
    raw = raw_scores.get(status, 0.0)
    # 超时惩罚：超过 10 秒开始线性增长，50 秒后达到上限 0.2
    duration_penalty = min(0.2, max(0.0, (duration_ms - 10_000) / 50_000))
    new_score = raw * confidence - duration_penalty
    # 指数移动平均 + 范围夹紧
    return max(0.0, min(1.0, _ALPHA * new_score + (1 - _ALPHA) * old_utility))


class SkillMetricsStore(Protocol):
    """技能指标存储的抽象接口。"""

    def record_execution(self, skill_id: str, status: str, confidence: float, duration_ms: float) -> None:
        """记录一次技能执行结果并更新指标。"""
        ...

    def get_utility(self, skill_id: str) -> float:
        """获取指定技能的当前效用评分。"""
        ...

    def get_all_metrics(self) -> dict[str, SkillMetrics]:
        """获取所有已记录技能的指标快照。"""
        ...


class InMemorySkillMetricsStore:
    """基于内存字典的技能指标存储实现。

    适用于单次运行和测试场景，进程结束后数据丢失。
    """

    def __init__(self) -> None:
        # skill_id -> SkillMetrics 的映射
        self._data: dict[str, SkillMetrics] = {}

    def record_execution(self, skill_id: str, status: str, confidence: float, duration_ms: float) -> None:
        """记录一次执行并更新内存中的指标。"""
        prev = self._data.get(skill_id)
        if prev is None:
            # 首次执行，初始化零值指标
            prev = SkillMetrics(
                skill_id=skill_id,
                execution_count=0,
                success_count=0,
                fail_count=0,
                avg_duration_ms=0.0,
                utility_score=_DEFAULT_UTILITY,
            )

        new_count = prev.execution_count + 1
        # 在线均值更新：avg_new = avg_old + (x - avg_old) / n
        new_avg = prev.avg_duration_ms + (duration_ms - prev.avg_duration_ms) / new_count
        is_success = status == "success"
        is_fail = status in ("failed", "needs_replan")

        self._data[skill_id] = SkillMetrics(
            skill_id=skill_id,
            execution_count=new_count,
            success_count=prev.success_count + (1 if is_success else 0),
            fail_count=prev.fail_count + (1 if is_fail else 0),
            avg_duration_ms=new_avg,
            utility_score=_compute_new_utility(prev.utility_score, status, confidence, duration_ms),
        )

    def get_utility(self, skill_id: str) -> float:
        """返回指定技能的效用评分，未记录过则返回默认值。"""
        entry = self._data.get(skill_id)
        return entry.utility_score if entry is not None else _DEFAULT_UTILITY

    def get_all_metrics(self) -> dict[str, SkillMetrics]:
        """返回全部指标的浅拷贝。"""
        return dict(self._data)


class SqliteSkillMetricsStore:
    """基于 SQLite 的技能指标持久化存储。

    数据存储在 ``skill_metrics`` 表中，使用 UPSERT 语句保证幂等写入。

    参数
    ----------
    conn : sqlite3.Connection
        已初始化建表的 SQLite 连接。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn  # SQLite 数据库连接

    def record_execution(self, skill_id: str, status: str, confidence: float, duration_ms: float) -> None:
        """记录一次执行并持久化更新指标。

        先读取已有记录，计算新值后通过 UPSERT 写回。
        """
        row = self._conn.execute(
            "SELECT execution_count, success_count, fail_count, avg_duration_ms, utility_score "
            "FROM skill_metrics WHERE skill_id = ?",
            (skill_id,),
        ).fetchone()

        if row is None:
            # 该技能尚无记录，使用默认初始值
            old_count, old_success, old_fail, old_avg, old_utility = 0, 0, 0, 0.0, _DEFAULT_UTILITY
        else:
            old_count, old_success, old_fail, old_avg, old_utility = (
                row["execution_count"],
                row["success_count"],
                row["fail_count"],
                row["avg_duration_ms"],
                row["utility_score"],
            )

        new_count = old_count + 1
        # 在线均值更新
        new_avg = old_avg + (duration_ms - old_avg) / new_count
        is_success = status == "success"
        is_fail = status in ("failed", "needs_replan")
        new_utility = _compute_new_utility(old_utility, status, confidence, duration_ms)

        # UPSERT: 存在则更新，不存在则插入
        self._conn.execute(
            """INSERT INTO skill_metrics
                (skill_id, execution_count, success_count, fail_count, avg_duration_ms, utility_score, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(skill_id) DO UPDATE SET
                execution_count = excluded.execution_count,
                success_count   = excluded.success_count,
                fail_count      = excluded.fail_count,
                avg_duration_ms = excluded.avg_duration_ms,
                utility_score   = excluded.utility_score,
                updated_at      = excluded.updated_at
            """,
            (
                skill_id,
                new_count,
                old_success + (1 if is_success else 0),
                old_fail + (1 if is_fail else 0),
                new_avg,
                new_utility,
                _now_iso(),
            ),
        )
        self._conn.commit()

    def get_utility(self, skill_id: str) -> float:
        """查询指定技能的效用评分，未记录则返回默认值。"""
        row = self._conn.execute(
            "SELECT utility_score FROM skill_metrics WHERE skill_id = ?", (skill_id,),
        ).fetchone()
        return float(row["utility_score"]) if row is not None else _DEFAULT_UTILITY

    def get_all_metrics(self) -> dict[str, SkillMetrics]:
        """从数据库加载全部技能指标。"""
        rows = self._conn.execute("SELECT * FROM skill_metrics").fetchall()
        return {
            row["skill_id"]: SkillMetrics(
                skill_id=row["skill_id"],
                execution_count=row["execution_count"],
                success_count=row["success_count"],
                fail_count=row["fail_count"],
                avg_duration_ms=row["avg_duration_ms"],
                utility_score=row["utility_score"],
            )
            for row in rows
        }
