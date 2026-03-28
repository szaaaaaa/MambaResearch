from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.dynamic_os.contracts.artifact import ArtifactRecord, now_iso as _now_iso
from src.dynamic_os.contracts.observation import Observation


@dataclass(frozen=True)
class ResearchMemory:
    run_id: str
    user_request: str
    topics: list[str] = field(default_factory=list)
    key_papers: list[dict[str, str]] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    quality_score: float = 0.0


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

class UserMemoryStore(Protocol):
    def save_research_memory(self, memory: ResearchMemory) -> None: ...
    def find_relevant_memories(self, query: str, top_k: int = 5) -> list[ResearchMemory]: ...
    def update_profile(self, key: str, value: Any) -> None: ...
    def get_profile(self) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# 关键词相关度
# ---------------------------------------------------------------------------

def _keyword_relevance(query: str, memory: ResearchMemory) -> float:
    query_tokens = set(query.lower().split())
    if not query_tokens:
        return 0.0
    memory_tokens: set[str] = set(memory.user_request.lower().split())
    for topic in memory.topics:
        memory_tokens.update(topic.lower().split())
    return len(query_tokens & memory_tokens) / len(query_tokens)


# ---------------------------------------------------------------------------
# InMemory 实现
# ---------------------------------------------------------------------------

class InMemoryUserMemoryStore:
    def __init__(self) -> None:
        self._memories: list[ResearchMemory] = []
        self._profile: dict[str, Any] = {}

    def save_research_memory(self, memory: ResearchMemory) -> None:
        self._memories.append(memory)

    def find_relevant_memories(self, query: str, top_k: int = 5) -> list[ResearchMemory]:
        scored = [(m, _keyword_relevance(query, m)) for m in self._memories]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [m for m, score in scored[:top_k] if score > 0.0]

    def update_profile(self, key: str, value: Any) -> None:
        self._profile[key] = value

    def get_profile(self) -> dict[str, Any]:
        return dict(self._profile)


# ---------------------------------------------------------------------------
# SQLite 实现
# ---------------------------------------------------------------------------

class SqliteUserMemoryStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save_research_memory(self, memory: ResearchMemory) -> None:
        self._conn.execute(
            """INSERT INTO research_memory
                (run_id, user_request, topics_json, key_papers_json,
                 methods_json, findings_json, quality_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                memory.run_id,
                memory.user_request,
                json.dumps(memory.topics, ensure_ascii=False),
                json.dumps(memory.key_papers, ensure_ascii=False),
                json.dumps(memory.methods, ensure_ascii=False),
                json.dumps(memory.findings, ensure_ascii=False),
                memory.quality_score,
                _now_iso(),
            ),
        )
        self._conn.commit()

    def find_relevant_memories(self, query: str, top_k: int = 5) -> list[ResearchMemory]:
        rows = self._conn.execute(
            "SELECT run_id, user_request, topics_json, key_papers_json, "
            "methods_json, findings_json, quality_score FROM research_memory"
        ).fetchall()
        memories = [_row_to_memory(r) for r in rows]
        scored = [(m, _keyword_relevance(query, m)) for m in memories]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [m for m, score in scored[:top_k] if score > 0.0]

    def update_profile(self, key: str, value: Any) -> None:
        self._conn.execute(
            """INSERT INTO user_profile (key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at""",
            (key, json.dumps(value, ensure_ascii=False), _now_iso()),
        )
        self._conn.commit()

    def get_profile(self) -> dict[str, Any]:
        rows = self._conn.execute("SELECT key, value_json FROM user_profile").fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}


def _row_to_memory(row: sqlite3.Row) -> ResearchMemory:
    return ResearchMemory(
        run_id=row["run_id"],
        user_request=row["user_request"] or "",
        topics=json.loads(row["topics_json"] or "[]"),
        key_papers=json.loads(row["key_papers_json"] or "[]"),
        methods=json.loads(row["methods_json"] or "[]"),
        findings=json.loads(row["findings_json"] or "[]"),
        quality_score=float(row["quality_score"] or 0.0),
    )


# ---------------------------------------------------------------------------
# 记忆提取（纯规则，无 LLM 调用）
# ---------------------------------------------------------------------------

def extract_research_memory(
    *,
    run_id: str,
    user_request: str,
    artifacts: list[ArtifactRecord],
    observations: list[Observation],
) -> ResearchMemory:
    """从一次 run 的产出中提取研究记忆。"""
    topics: list[str] = []
    key_papers: list[dict[str, str]] = []
    methods: list[str] = []
    findings: list[str] = []

    for art in artifacts:
        p = art.payload
        if art.artifact_type == "TopicBrief":
            topic = p.get("topic", "")
            if topic:
                topics.append(topic)
            for q in p.get("research_questions", []):
                if isinstance(q, str) and q.strip():
                    topics.append(q.strip())

        elif art.artifact_type == "SearchPlan":
            topic = p.get("topic", "")
            if topic and topic not in topics:
                topics.append(topic)

        elif art.artifact_type == "SourceSet":
            for src in p.get("sources", []):
                if not isinstance(src, dict):
                    continue
                paper_id = str(src.get("paper_id", "")).strip()
                title = str(src.get("title", "")).strip()
                if paper_id or title:
                    key_papers.append({"paper_id": paper_id, "title": title})

        elif art.artifact_type == "EvidenceMap":
            for item in p.get("evidence_items", []):
                if isinstance(item, dict):
                    summary = str(item.get("summary", "")).strip()
                    if summary:
                        methods.append(summary[:120])

        elif art.artifact_type == "ResearchReport":
            report = p.get("report", "")
            if isinstance(report, str) and report.strip():
                # 取前 500 字符作为摘要
                findings.append(report.strip()[:500])

    # quality_score: 成功率
    total = len(observations) if observations else 0
    success_count = sum(1 for obs in observations if obs.status.value == "success")
    quality_score = success_count / total if total > 0 else 0.0

    return ResearchMemory(
        run_id=run_id,
        user_request=user_request,
        topics=topics[:20],
        key_papers=key_papers[:50],
        methods=methods[:20],
        findings=findings[:5],
        quality_score=round(quality_score, 3),
    )
