"""知识图谱存储 —— 基于 NetworkX + SQLite 的研究知识图谱。

本模块实现了 Dynamic Research OS 的知识图谱持久化层。
知识图谱用于结构化存储研究过程中发现的实体及其关系，
例如论文、概念、方法、数据集、实验结果、研究者之间的关联。

架构设计
--------
- **内存层**: 使用 NetworkX 有向图维护图结构，支持快速遍历和查询
- **持久层**: 通过 SQLite 表（kg_nodes / kg_edges）持久化节点和边
- 初始化时从 SQLite 加载全量数据到 NetworkX；写入时同步双写

节点类型（NODE_*）
------------------
- Paper: 论文
- Concept: 研究概念 / 术语
- Method: 方法 / 算法
- Dataset: 数据集
- Result: 实验结果
- Researcher: 研究者

边类型（EDGE_*）
----------------
- USES: 使用（论文→方法、论文→数据集）
- EVALUATES_ON: 在某数据集上评估
- ACHIEVES: 达成某结果
- CITES: 引用
- PROPOSES: 提出（论文→方法）
- RELATED_TO: 相关
- OUTPERFORMS: 优于
- BELONGS_TO: 属于
- AUTHORED_BY: 作者
- VARIANT_OF: 变体
"""

from __future__ import annotations

import json
import sqlite3

from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# 节点类型常量
# ---------------------------------------------------------------------------
NODE_PAPER = "Paper"          # 论文
NODE_CONCEPT = "Concept"      # 研究概念 / 术语
NODE_METHOD = "Method"        # 方法 / 算法
NODE_DATASET = "Dataset"      # 数据集
NODE_RESULT = "Result"        # 实验结果
NODE_RESEARCHER = "Researcher"  # 研究者

# 所有合法节点类型的元组，可用于校验
ALL_NODE_TYPES = (NODE_PAPER, NODE_CONCEPT, NODE_METHOD, NODE_DATASET, NODE_RESULT, NODE_RESEARCHER)

# ---------------------------------------------------------------------------
# 边（关系）类型常量
# ---------------------------------------------------------------------------
EDGE_USES = "USES"                  # 使用（如论文使用某方法）
EDGE_EVALUATES_ON = "EVALUATES_ON"  # 在某数据集上评估
EDGE_ACHIEVES = "ACHIEVES"          # 达成某实验结果
EDGE_CITES = "CITES"                # 引用另一篇论文
EDGE_PROPOSES = "PROPOSES"          # 提出某方法 / 概念
EDGE_RELATED_TO = "RELATED_TO"      # 通用相关关系
EDGE_OUTPERFORMS = "OUTPERFORMS"    # 性能优于
EDGE_BELONGS_TO = "BELONGS_TO"      # 归属关系
EDGE_AUTHORED_BY = "AUTHORED_BY"    # 论文作者
EDGE_VARIANT_OF = "VARIANT_OF"      # 方法变体

# 所有合法边类型的元组
ALL_EDGE_TYPES = (
    EDGE_USES,
    EDGE_EVALUATES_ON,
    EDGE_ACHIEVES,
    EDGE_CITES,
    EDGE_PROPOSES,
    EDGE_RELATED_TO,
    EDGE_OUTPERFORMS,
    EDGE_BELONGS_TO,
    EDGE_AUTHORED_BY,
    EDGE_VARIANT_OF,
)


class KnowledgeGraph:
    """研究知识图谱。

    同时维护一个 NetworkX 有向图（内存快速查询）和一个 SQLite
    数据库连接（持久化）。所有写操作双写到两个后端。

    参数
    ----------
    conn : sqlite3.Connection
        已初始化建表的 SQLite 连接（由 ``init_knowledge_db`` 创建）。
    run_id : str
        当前运行 ID，新增节点/边时会标记此 ID 以区分不同运行。
    """

    def __init__(self, conn: sqlite3.Connection, run_id: str) -> None:
        import networkx  # 延迟导入 - 可选依赖

        self._graph: networkx.DiGraph = networkx.DiGraph()  # 内存中的有向图
        self._conn: sqlite3.Connection | None = conn        # SQLite 持久化连接
        self._run_id = run_id                                # 当前运行标识

        # 启用 Row 工厂以支持按列名访问
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 从 SQLite 加载全量节点到 NetworkX
        for row in cur.execute("SELECT id, node_type, properties_json, embedding_id, run_id FROM kg_nodes"):
            self._graph.add_node(
                row["id"],
                node_type=row["node_type"],
                properties=json.loads(row["properties_json"]),
                embedding_id=row["embedding_id"],
                run_id=row["run_id"],
            )

        # 从 SQLite 加载全量边到 NetworkX
        for row in cur.execute(
            "SELECT id, source_id, target_id, relation_type, properties_json, run_id FROM kg_edges"
        ):
            self._graph.add_edge(
                row["source_id"],
                row["target_id"],
                id=row["id"],
                relation_type=row["relation_type"],
                properties=json.loads(row["properties_json"]),
                run_id=row["run_id"],
            )

    def add_node(
        self, *, node_id: str, node_type: str, properties: dict, embedding_id: str = ""
    ) -> None:
        """添加一个节点到知识图谱。

        同时写入 NetworkX 内存图和 SQLite 持久层。
        若节点 ID 已存在，SQLite 侧使用 INSERT OR IGNORE 跳过。

        参数
        ----------
        node_id : str
            节点唯一标识，通常为 ``{类型}:{名称}`` 格式。
        node_type : str
            节点类型，应为 ALL_NODE_TYPES 之一。
        properties : dict
            节点属性字典（如论文标题、摘要等）。
        embedding_id : str, optional
            关联的向量嵌入 ID，默认为空串。
        """
        self._graph.add_node(
            node_id,
            node_type=node_type,
            properties=properties,
            embedding_id=embedding_id,
            run_id=self._run_id,
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO kg_nodes (id, node_type, properties_json, embedding_id, run_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                node_id,
                node_type,
                json.dumps(properties or {}, ensure_ascii=False),
                embedding_id,
                self._run_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def add_edge(
        self,
        *,
        source_id: str,
        target_id: str,
        relation_type: str,
        properties: dict | None = None,
    ) -> None:
        """添加一条有向边到知识图谱。

        仅当源节点和目标节点均已存在时才执行插入。
        边 ID 自动生成，格式为 ``{source_id}__{relation_type}__{target_id}``。

        参数
        ----------
        source_id : str
            源节点 ID。
        target_id : str
            目标节点 ID。
        relation_type : str
            关系类型，应为 ALL_EDGE_TYPES 之一。
        properties : dict | None, optional
            边的附加属性，默认为空字典。
        """
        # 若任一端点不存在，静默跳过
        if source_id not in self._graph or target_id not in self._graph:
            return

        # 根据三元组生成确定性边 ID
        edge_id = f"{source_id}__{relation_type}__{target_id}"
        props = properties or {}

        self._graph.add_edge(
            source_id,
            target_id,
            id=edge_id,
            relation_type=relation_type,
            properties=props,
            run_id=self._run_id,
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO kg_edges (id, source_id, target_id, relation_type, properties_json, run_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                edge_id,
                source_id,
                target_id,
                relation_type,
                json.dumps(props, ensure_ascii=False),
                self._run_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def neighbors(self, node_id: str, relation_type: str | None = None) -> list[dict]:
        """获取指定节点的后继邻居。

        参数
        ----------
        node_id : str
            起始节点 ID。
        relation_type : str | None, optional
            若指定，则只返回该关系类型的邻居。

        返回
        -------
        list[dict]
            邻居节点的属性字典列表。
        """
        if node_id not in self._graph:
            return []

        result: list[dict] = []
        for successor in self._graph.successors(node_id):
            edge_data = self._graph.edges[node_id, successor]
            # 按关系类型过滤
            if relation_type is not None and edge_data.get("relation_type") != relation_type:
                continue
            result.append(dict(self._graph.nodes[successor]))
        return result

    def search_by_type(self, node_type: str) -> list[dict]:
        """按类型检索所有节点。

        参数
        ----------
        node_type : str
            目标节点类型（如 NODE_PAPER）。

        返回
        -------
        list[dict]
            匹配节点的属性字典列表，每项包含 ``id`` 字段。
        """
        return [
            {"id": n, **data}
            for n, data in self._graph.nodes(data=True)
            if data.get("node_type") == node_type
        ]

    def summary_for_planner(self) -> dict:
        """生成面向 Planner 的知识图谱摘要。

        返回
        -------
        dict
            包含节点总数、边总数、各类型节点计数、涉及的运行 ID 列表。
        """
        node_types: dict[str, int] = {}  # 节点类型 -> 数量
        run_ids_set: set[str] = set()    # 出现过的运行 ID 集合

        for _, data in self._graph.nodes(data=True):
            nt = data.get("node_type", "")
            node_types[nt] = node_types.get(nt, 0) + 1
            rid = data.get("run_id")
            if rid:
                run_ids_set.add(rid)

        return {
            "node_count": self._graph.number_of_nodes(),
            "edge_count": self._graph.number_of_edges(),
            "node_types": node_types,
            "run_ids": list(run_ids_set),
        }

    def close(self) -> None:
        """释放 SQLite 连接引用（不关闭连接本身）。"""
        self._conn = None
