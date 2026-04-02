"""内存存储后端 —— 基于 Python 字典 / 列表的存储实现。

本模块定义了三组核心存储接口（Protocol）及其纯内存实现：

1. **ArtifactStore** — 制品（研究产物）的增删查接口
2. **ObservationStore** — 节点执行观测记录的追加与查询
3. **PlanStore** — 执行计划（RoutePlan）的版本管理

内存实现适用于单次运行 / 测试场景，数据不持久化。
生产环境使用 ``sqlite_store`` 中的 SQLite 实现替代。
"""

from __future__ import annotations

from typing import Protocol

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.observation import Observation
from src.dynamic_os.contracts.route_plan import RoutePlan


# ---------------------------------------------------------------------------
# 抽象接口（Protocol）
# ---------------------------------------------------------------------------


class ArtifactStore(Protocol):
    """制品存储接口。

    制品（Artifact）是技能执行后产出的结构化数据，例如论文摘要、
    搜索计划、证据图等。每个制品有唯一 ID 和类型。
    """

    def save(self, record: ArtifactRecord) -> None:
        """保存或更新一条制品记录。"""
        ...

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        """根据 ID 获取单条制品，不存在返回 None。"""
        ...

    def list_by_type(self, artifact_type: str) -> list[ArtifactRecord]:
        """按制品类型列出所有匹配记录。"""
        ...

    def list_all(self) -> list[ArtifactRecord]:
        """列出当前作用域内的全部制品。"""
        ...

    def summary(self) -> list[dict[str, str]]:
        """返回制品摘要列表，供 Planner 快速浏览。"""
        ...


class ObservationStore(Protocol):
    """观测记录存储接口。

    每次技能执行结束后，Executor 会写入一条 Observation，
    记录执行状态、耗时、产出制品等元数据，供 Planner 决策参考。
    """

    def save(self, obs: Observation) -> None:
        """追加一条观测记录。"""
        ...

    def list_latest(self, n: int = 5) -> list[Observation]:
        """获取最近 n 条观测记录（按时间倒序）。"""
        ...

    def list_by_node(self, node_id: str) -> list[Observation]:
        """获取指定计划节点的全部观测记录。"""
        ...


class PlanStore(Protocol):
    """执行计划存储接口。

    RoutePlan 是 Planner 生成的 DAG 执行计划，每次重规划会产生
    新版本。PlanStore 维护计划的版本历史。
    """

    def save(self, plan: RoutePlan) -> None:
        """保存一个新版本的执行计划。"""
        ...

    def get_latest(self) -> RoutePlan | None:
        """获取最新版本的执行计划，无计划时返回 None。"""
        ...

    def list_all(self) -> list[RoutePlan]:
        """列出全部历史计划版本。"""
        ...


# ---------------------------------------------------------------------------
# 内存实现
# ---------------------------------------------------------------------------


class InMemoryArtifactStore:
    """基于字典的内存制品存储。

    以 artifact_id 为键存储制品，支持按类型过滤和摘要输出。
    适用于单次运行和测试场景。
    """

    def __init__(self) -> None:
        # artifact_id -> ArtifactRecord 的映射表
        self._records: dict[str, ArtifactRecord] = {}

    def save(self, record: ArtifactRecord) -> None:
        """保存制品，若 ID 已存在则覆盖。"""
        self._records[record.artifact_id] = record

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        """按 ID 查找制品。"""
        return self._records.get(artifact_id)

    def list_by_type(self, artifact_type: str) -> list[ArtifactRecord]:
        """过滤并返回指定类型的全部制品。"""
        return [record for record in self._records.values() if record.artifact_type == artifact_type]

    def list_all(self) -> list[ArtifactRecord]:
        """返回全部已存储的制品。"""
        return list(self._records.values())

    def summary(self) -> list[dict[str, str]]:
        """生成制品摘要列表，包含 ID、类型、引用路径和生产者角色。"""
        return [
            {
                "artifact_id": record.artifact_id,
                "artifact_type": record.artifact_type,
                # 制品引用格式: artifact:{类型}:{ID}
                "artifact_ref": f"artifact:{record.artifact_type}:{record.artifact_id}",
                "producer_role": record.producer_role.value,
            }
            for record in self._records.values()
        ]


class InMemoryObservationStore:
    """基于列表的内存观测记录存储。

    按追加顺序保存观测，支持按时间和节点 ID 检索。
    """

    def __init__(self) -> None:
        # 按时间顺序追加的观测列表
        self._observations: list[Observation] = []

    def save(self, obs: Observation) -> None:
        """追加一条观测记录到末尾。"""
        self._observations.append(obs)

    def list_latest(self, n: int = 5) -> list[Observation]:
        """取最近 n 条观测记录（切片末尾）。"""
        return self._observations[-n:]

    def list_by_node(self, node_id: str) -> list[Observation]:
        """返回与指定计划节点关联的全部观测。"""
        return [obs for obs in self._observations if obs.node_id == node_id]


class InMemoryPlanStore:
    """基于列表的内存执行计划存储。

    按版本顺序追加计划，最新版本始终在列表末尾。
    """

    def __init__(self) -> None:
        # 按版本顺序的计划列表
        self._plans: list[RoutePlan] = []

    def save(self, plan: RoutePlan) -> None:
        """追加一个新版本的计划。"""
        self._plans.append(plan)

    def get_latest(self) -> RoutePlan | None:
        """获取最新计划，列表为空时返回 None。"""
        if not self._plans:
            return None
        return self._plans[-1]

    def list_all(self) -> list[RoutePlan]:
        """返回全部历史计划（浅拷贝）。"""
        return list(self._plans)
