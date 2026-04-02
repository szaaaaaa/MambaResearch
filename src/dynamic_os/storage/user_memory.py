"""用户记忆存储 —— 跨运行的研究记忆与用户画像管理。

本模块提供两项核心能力：

1. **研究记忆持久化** (``ResearchMemory`` + ``UserMemoryStore``)
   每次研究运行结束后，系统自动提取关键信息（主题、论文、方法、发现）
   保存为结构化记忆。后续运行可检索历史记忆，实现知识积累。

2. **用户画像** (``update_profile`` / ``get_profile``)
   存储用户偏好和行为特征的键值对，供个性化策略参考。

记忆检索策略
-----------
当前版本使用基于关键词重叠的简单相关度算法 (``_keyword_relevance``)。
将查询分词后与记忆的请求文本和主题取交集，计算重叠率作为相关度分数。

记忆提取流程
-----------
``extract_research_memory`` 函数从一次运行的制品和观测中，
按规则提取结构化记忆，不依赖 LLM 调用：
- TopicBrief → 主题和研究问题
- SearchPlan → 补充主题
- SourceSet → 关键论文列表
- EvidenceMap → 方法摘要
- ResearchReport → 研究发现（取前 500 字符）
- 观测成功率 → 质量评分
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.dynamic_os.contracts.artifact import ArtifactRecord, now_iso as _now_iso
from src.dynamic_os.contracts.observation import Observation


@dataclass(frozen=True)
class ResearchMemory:
    """单次研究运行的结构化记忆摘要（不可变）。

    参数
    ----------
    run_id : str
        来源运行 ID。
    user_request : str
        用户的原始研究请求文本。
    topics : list[str]
        涉及的研究主题和问题。
    key_papers : list[dict[str, str]]
        关键论文列表，每项含 paper_id 和 title。
    methods : list[str]
        涉及的研究方法摘要。
    findings : list[str]
        主要研究发现。
    quality_score : float
        运行质量评分（基于观测成功率），范围 [0, 1]。
    """

    run_id: str
    user_request: str
    topics: list[str] = field(default_factory=list)
    key_papers: list[dict[str, str]] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    quality_score: float = 0.0


# ---------------------------------------------------------------------------
# 抽象接口
# ---------------------------------------------------------------------------

class UserMemoryStore(Protocol):
    """用户记忆存储的抽象接口。

    包含研究记忆的存取和用户画像的增查两组操作。
    """

    def save_research_memory(self, memory: ResearchMemory) -> None:
        """保存一条研究记忆。"""
        ...

    def find_relevant_memories(self, query: str, top_k: int = 5) -> list[ResearchMemory]:
        """根据查询检索最相关的历史研究记忆。"""
        ...

    def update_profile(self, key: str, value: Any) -> None:
        """更新用户画像的某个键值。"""
        ...

    def get_profile(self) -> dict[str, Any]:
        """获取完整的用户画像字典。"""
        ...


# ---------------------------------------------------------------------------
# 关键词相关度计算
# ---------------------------------------------------------------------------

def _keyword_relevance(query: str, memory: ResearchMemory) -> float:
    """基于关键词重叠率计算查询与记忆的相关度。

    将查询和记忆文本（请求 + 主题）分别分词后取交集，
    返回交集大小与查询词数的比值。

    参数
    ----------
    query : str
        检索查询字符串。
    memory : ResearchMemory
        待比较的研究记忆。

    返回
    -------
    float
        相关度分数，范围 [0, 1]。查询为空时返回 0。
    """
    query_tokens = set(query.lower().split())
    if not query_tokens:
        return 0.0
    # 记忆侧：合并用户请求和各主题的分词
    memory_tokens: set[str] = set(memory.user_request.lower().split())
    for topic in memory.topics:
        memory_tokens.update(topic.lower().split())
    return len(query_tokens & memory_tokens) / len(query_tokens)


# ---------------------------------------------------------------------------
# 内存实现
# ---------------------------------------------------------------------------

class InMemoryUserMemoryStore:
    """基于列表 / 字典的内存用户记忆存储。

    适用于单次运行和测试，进程结束后数据丢失。
    """

    def __init__(self) -> None:
        self._memories: list[ResearchMemory] = []  # 研究记忆列表
        self._profile: dict[str, Any] = {}          # 用户画像字典

    def save_research_memory(self, memory: ResearchMemory) -> None:
        """追加一条研究记忆。"""
        self._memories.append(memory)

    def find_relevant_memories(self, query: str, top_k: int = 5) -> list[ResearchMemory]:
        """按关键词相关度检索记忆，返回得分 > 0 的 top_k 条。"""
        scored = [(m, _keyword_relevance(query, m)) for m in self._memories]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [m for m, score in scored[:top_k] if score > 0.0]

    def update_profile(self, key: str, value: Any) -> None:
        """设置或覆盖用户画像中的某个键。"""
        self._profile[key] = value

    def get_profile(self) -> dict[str, Any]:
        """返回用户画像的浅拷贝。"""
        return dict(self._profile)


# ---------------------------------------------------------------------------
# SQLite 实现
# ---------------------------------------------------------------------------

class SqliteUserMemoryStore:
    """基于 SQLite 的用户记忆持久化存储。

    研究记忆存储在 ``research_memory`` 表，用户画像存储在 ``user_profile`` 表。

    参数
    ----------
    conn : sqlite3.Connection
        已初始化建表的 SQLite 连接。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn  # SQLite 数据库连接

    def save_research_memory(self, memory: ResearchMemory) -> None:
        """将研究记忆序列化后存入数据库。"""
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
        """从数据库加载全部记忆后按关键词相关度排序返回。

        注意：当前实现为全表扫描 + 内存排序，适用于记忆量较小的场景。
        大规模场景应考虑引入向量检索或全文索引。
        """
        rows = self._conn.execute(
            "SELECT run_id, user_request, topics_json, key_papers_json, "
            "methods_json, findings_json, quality_score FROM research_memory"
        ).fetchall()
        memories = [_row_to_memory(r) for r in rows]
        scored = [(m, _keyword_relevance(query, m)) for m in memories]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [m for m, score in scored[:top_k] if score > 0.0]

    def update_profile(self, key: str, value: Any) -> None:
        """更新用户画像键值对，已存在则覆盖。"""
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
        """加载并返回完整的用户画像字典。"""
        rows = self._conn.execute("SELECT key, value_json FROM user_profile").fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}


def _row_to_memory(row: sqlite3.Row) -> ResearchMemory:
    """将 SQLite 行数据转换为 ResearchMemory 数据对象。

    对可能为 NULL 的字段提供安全的默认值处理。
    """
    return ResearchMemory(
        run_id=row["run_id"],
        user_request=row["user_request"] or "",             # NULL -> 空串
        topics=json.loads(row["topics_json"] or "[]"),       # NULL -> 空列表
        key_papers=json.loads(row["key_papers_json"] or "[]"),
        methods=json.loads(row["methods_json"] or "[]"),
        findings=json.loads(row["findings_json"] or "[]"),
        quality_score=float(row["quality_score"] or 0.0),    # NULL -> 0.0
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
    """从一次运行的产出中提取结构化研究记忆。

    纯规则实现，不依赖 LLM。按制品类型逐一提取关键信息，
    并基于观测成功率计算质量评分。

    参数
    ----------
    run_id : str
        运行 ID。
    user_request : str
        用户原始请求。
    artifacts : list[ArtifactRecord]
        本次运行产出的全部制品。
    observations : list[Observation]
        本次运行的全部观测记录。

    返回
    -------
    ResearchMemory
        提取后的结构化记忆，各列表有上限截断以控制存储大小。
    """
    topics: list[str] = []
    key_papers: list[dict[str, str]] = []
    methods: list[str] = []
    findings: list[str] = []

    for art in artifacts:
        p = art.payload

        # TopicBrief: 提取研究主题和研究问题
        if art.artifact_type == "TopicBrief":
            topic = p.get("topic", "")
            if topic:
                topics.append(topic)
            for q in p.get("research_questions", []):
                if isinstance(q, str) and q.strip():
                    topics.append(q.strip())

        # SearchPlan: 补充主题（去重）
        elif art.artifact_type == "SearchPlan":
            topic = p.get("topic", "")
            if topic and topic not in topics:
                topics.append(topic)

        # SourceSet: 提取关键论文的 ID 和标题
        elif art.artifact_type == "SourceSet":
            for src in p.get("sources", []):
                if not isinstance(src, dict):
                    continue
                paper_id = str(src.get("paper_id", "")).strip()
                title = str(src.get("title", "")).strip()
                if paper_id or title:
                    key_papers.append({"paper_id": paper_id, "title": title})

        # EvidenceMap: 提取证据摘要作为方法描述
        elif art.artifact_type == "EvidenceMap":
            for item in p.get("evidence_items", []):
                if isinstance(item, dict):
                    summary = str(item.get("summary", "")).strip()
                    if summary:
                        methods.append(summary[:120])  # 截断到 120 字符

        # ResearchReport: 提取报告正文前 500 字符作为发现摘要
        elif art.artifact_type == "ResearchReport":
            report = p.get("report", "")
            if isinstance(report, str) and report.strip():
                findings.append(report.strip()[:500])

    # 质量评分：基于观测的成功率
    total = len(observations) if observations else 0
    success_count = sum(1 for obs in observations if obs.status.value == "success")
    quality_score = success_count / total if total > 0 else 0.0

    # 返回记忆，各列表设置上限防止数据膨胀
    return ResearchMemory(
        run_id=run_id,
        user_request=user_request,
        topics=topics[:20],          # 最多 20 个主题
        key_papers=key_papers[:50],  # 最多 50 篇论文
        methods=methods[:20],        # 最多 20 条方法
        findings=findings[:5],       # 最多 5 条发现
        quality_score=round(quality_score, 3),
    )
