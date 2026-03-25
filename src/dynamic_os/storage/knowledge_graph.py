from __future__ import annotations

import json
import sqlite3

from datetime import datetime, timezone

# Node types
NODE_PAPER = "Paper"
NODE_CONCEPT = "Concept"
NODE_METHOD = "Method"
NODE_DATASET = "Dataset"
NODE_RESULT = "Result"
NODE_RESEARCHER = "Researcher"

ALL_NODE_TYPES = (NODE_PAPER, NODE_CONCEPT, NODE_METHOD, NODE_DATASET, NODE_RESULT, NODE_RESEARCHER)

# Edge types
EDGE_USES = "USES"
EDGE_EVALUATES_ON = "EVALUATES_ON"
EDGE_ACHIEVES = "ACHIEVES"
EDGE_CITES = "CITES"
EDGE_PROPOSES = "PROPOSES"
EDGE_RELATED_TO = "RELATED_TO"
EDGE_OUTPERFORMS = "OUTPERFORMS"
EDGE_BELONGS_TO = "BELONGS_TO"
EDGE_AUTHORED_BY = "AUTHORED_BY"
EDGE_VARIANT_OF = "VARIANT_OF"

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
    def __init__(self, conn: sqlite3.Connection, run_id: str) -> None:
        import networkx  # lazy import – optional dependency
        self._graph: networkx.DiGraph = networkx.DiGraph()
        self._conn: sqlite3.Connection | None = conn
        self._run_id = run_id

        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        for row in cur.execute("SELECT id, node_type, properties_json, embedding_id, run_id FROM kg_nodes"):
            self._graph.add_node(
                row["id"],
                node_type=row["node_type"],
                properties=json.loads(row["properties_json"]),
                embedding_id=row["embedding_id"],
                run_id=row["run_id"],
            )

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
        if source_id not in self._graph or target_id not in self._graph:
            return

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
        if node_id not in self._graph:
            return []

        result: list[dict] = []
        for successor in self._graph.successors(node_id):
            edge_data = self._graph.edges[node_id, successor]
            if relation_type is not None and edge_data.get("relation_type") != relation_type:
                continue
            result.append(dict(self._graph.nodes[successor]))
        return result

    def search_by_type(self, node_type: str) -> list[dict]:
        return [
            {"id": n, **data}
            for n, data in self._graph.nodes(data=True)
            if data.get("node_type") == node_type
        ]

    def summary_for_planner(self) -> dict:
        node_types: dict[str, int] = {}
        run_ids_set: set[str] = set()

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
        self._conn = None
