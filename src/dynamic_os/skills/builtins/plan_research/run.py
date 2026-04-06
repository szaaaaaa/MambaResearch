from __future__ import annotations

import json
import re

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


# ---------------------------------------------------------------------------
# LLM 输出 schema
# ---------------------------------------------------------------------------

SEARCH_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "domain_topic": {
            "type": "string",
            "description": "The core research domain/subject extracted from user input. Must be a concise academic phrase, NOT a task instruction or format requirement.",
        },
        "research_questions": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 5,
            "description": "Specific research questions to investigate about the domain topic.",
        },
        "search_queries": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 6,
            "description": "English keyword-centric search strings for academic databases. Must contain ONLY domain terms, NO format/output requirements.",
        },
        "query_routes": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "use_academic": {"type": "boolean"},
                    "use_web": {"type": "boolean"},
                },
                "required": ["use_academic", "use_web"],
                "additionalProperties": False,
            },
        },
        "format_requirements": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Output format requests extracted from user input (e.g. 'include figures and tables', 'write in Chinese'). Empty array if none.",
        },
        "scope_constraints": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Scope/filtering constraints extracted from user input (e.g. 'last 3 years', 'focus on NLP'). Empty array if none.",
        },
        "content_focus": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific content emphasis requested by user (e.g. 'compare Transformer vs traditional methods'). Empty array if none.",
        },
        "recommended_sources": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Which academic search sources are relevant for this topic. "
                "Pick from: arxiv, semantic, openalex, crossref, dblp, pubmed, "
                "biorxiv, medrxiv, pmc, europepmc, google_scholar, core, "
                "openaire, doaj, base, zenodo, hal, ssrn, iacr, citeseerx. "
                "Select 3-6 sources that best match the research domain. "
                "CS/AI/ML → arxiv, semantic, dblp, openalex, crossref. "
                "Biomedical → pubmed, biorxiv, medrxiv, pmc, europepmc. "
                "General science → openalex, crossref, core, semantic. "
                "Cryptography → iacr, arxiv. "
                "Social science → ssrn, openalex, crossref."
            ),
        },
    },
    "required": [
        "domain_topic",
        "research_questions",
        "search_queries",
        "query_routes",
        "format_requirements",
        "scope_constraints",
        "content_focus",
        "recommended_sources",
    ],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# System prompt — 让 LLM 做语义拆分
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a research planning assistant. Your job is to decompose a user's research "
    "request into structured components. Return JSON only.\n\n"
    "The user input is a natural language request that may mix together:\n"
    "1. **Domain topic** — the actual research subject (e.g. 'time series forecasting', 'graph neural networks')\n"
    "2. **Format requirements** — how the output should look (e.g. '带图表引用' = include figure/table citations, '写一篇综述' = write a survey)\n"
    "3. **Scope constraints** — filtering criteria (e.g. '最近三年' = last 3 years, 'focus on medical domain')\n"
    "4. **Content focus** — specific angles or comparisons (e.g. '重点比较Transformer和传统方法' = compare Transformer vs traditional)\n"
    "5. **Task instructions** — meta-commands like 'help me', 'please generate' — these should be DISCARDED\n\n"
    "Rules:\n"
    "- domain_topic: Extract ONLY the research subject. '一篇带图表引用的时序' → domain_topic is '时序分析与预测' (time series analysis and forecasting), NOT '带图表引用的时序'.\n"
    "- search_queries: Must be in ENGLISH. Must contain ONLY domain-relevant academic keywords. "
    "NEVER include format words like 'with figure', 'with table', 'citation', 'survey format', 'review paper' in search queries. "
    "Generate 3-5 varied queries covering different aspects of the topic.\n"
    "- format_requirements: Capture any output format requests. If the user says '带图表引用', record it here, not in search_queries.\n"
    "- scope_constraints: Capture time ranges, domain restrictions, etc.\n"
    "- content_focus: Capture specific angles, comparisons, or emphasis requested.\n"
    "- query_routes: Use academic search by default. Enable web only for tools, code, products, or implementations.\n"
    "- recommended_sources: Select 3-6 sources that match the research domain. "
    "Do NOT include all sources — only those relevant to the topic.\n\n"
    "Examples:\n"
    "Input: '帮我写一篇带图表引用的时序预测综述'\n"
    "→ domain_topic: '时序预测'\n"
    "→ search_queries: ['time series forecasting survey', 'time series forecasting methods', 'deep learning time series prediction', 'time series forecasting benchmark evaluation']\n"
    "→ format_requirements: ['带图表引用', '综述形式']\n"
    "→ recommended_sources: ['arxiv', 'semantic', 'dblp', 'openalex', 'crossref']\n\n"
    "Input: 'survey on graph neural networks for drug discovery, last 3 years, compare GNN vs traditional ML'\n"
    "→ domain_topic: 'graph neural networks for drug discovery'\n"
    "→ search_queries: ['graph neural networks drug discovery', 'GNN molecular property prediction', 'deep learning drug design', 'graph-based virtual screening']\n"
    "→ format_requirements: ['survey']\n"
    "→ scope_constraints: ['last 3 years']\n"
    "→ content_focus: ['compare GNN vs traditional ML']\n"
    "→ recommended_sources: ['arxiv', 'semantic', 'pubmed', 'openalex', 'crossref']"
)


# ---------------------------------------------------------------------------
# 技能入口
# ---------------------------------------------------------------------------

async def run(ctx: SkillContext) -> SkillOutput:
    goal = ctx.user_request or ctx.goal
    raw_plan = await ctx.tools.llm_chat(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": goal},
        ],
        temperature=0.2,
        response_format=SEARCH_PLAN_SCHEMA,
    )
    parsed = _parse_structured_plan(raw_plan)

    # 提取各槽位，做基本校验
    topic = _normalize_text(str(parsed.get("domain_topic") or ""))
    if not topic:
        topic = _normalize_text(goal)
    research_questions = _clean_string_list(parsed.get("research_questions"))
    if not research_questions:
        research_questions = [f"What are the core problems, methods, and evidence for {topic}?"]
    search_queries = _clean_string_list(parsed.get("search_queries"))
    if not search_queries:
        search_queries = [topic, f"{topic} survey", f"{topic} methods"]

    # 确保搜索词是英文
    if any(_contains_cjk(q) for q in search_queries):
        search_queries = await _translate_queries(ctx, search_queries)

    query_routes = _normalize_query_routes(parsed.get("query_routes"), search_queries)
    format_requirements = _clean_string_list(parsed.get("format_requirements"))
    scope_constraints = _clean_string_list(parsed.get("scope_constraints"))
    content_focus = _clean_string_list(parsed.get("content_focus"))
    recommended_sources = _clean_string_list(parsed.get("recommended_sources"))
    if not recommended_sources:
        recommended_sources = ["arxiv", "semantic", "openalex", "crossref"]

    topic_brief = _artifact(
        ctx,
        "TopicBrief",
        {
            "topic": topic,
            "brief": f"研究主题：{topic}",
            "research_questions": research_questions,
            "format_requirements": format_requirements,
            "scope_constraints": scope_constraints,
            "content_focus": content_focus,
        },
    )
    search_plan = _artifact(
        ctx,
        "SearchPlan",
        {
            "topic": topic,
            "research_questions": research_questions,
            "search_queries": search_queries,
            "query_routes": query_routes,
            "recommended_sources": recommended_sources,
            "plan_text": f"研究主题：{topic}",
        },
    )
    return SkillOutput(
        success=True,
        output_artifacts=[topic_brief, search_plan],
        metadata={"query_count": len(search_queries), "topic": topic},
    )


# ---------------------------------------------------------------------------
# 工具函数（只保留必要的）
# ---------------------------------------------------------------------------

def _parse_structured_plan(raw_plan: str) -> dict:
    """解析 LLM 返回的 JSON。"""
    text = str(raw_plan or "").strip()
    fenced_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced_match:
        text = fenced_match.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _clean_string_list(raw: object) -> list[str]:
    """从 LLM 输出中提取非空字符串列表。"""
    if not isinstance(raw, list):
        return []
    return [_normalize_text(str(item)) for item in raw if _normalize_text(str(item))]


def _normalize_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    return normalized.strip(" \t\r\n\"'`.,;:!?()[]{}<>，。；：！？（）【】")


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


async def _translate_queries(ctx: SkillContext, queries: list[str]) -> list[str]:
    """将含中文的搜索词翻译为英文学术关键词。"""
    joined = "\n".join(queries)
    translated = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": "Translate the following search queries to English academic keyword phrases. Return one query per line, nothing else.",
            },
            {"role": "user", "content": joined},
        ],
        temperature=0.0,
        max_tokens=512,
    )
    lines = [line.strip() for line in translated.strip().splitlines() if line.strip()]
    if not lines or all(_contains_cjk(line) for line in lines):
        return queries
    return [line for line in lines if not _contains_cjk(line)][:5] or queries


def _normalize_query_routes(raw_routes: object, queries: list[str]) -> dict[str, dict[str, bool]]:
    """从 LLM 输出中提取路由决策，缺失时默认 academic。"""
    route_map = raw_routes if isinstance(raw_routes, dict) else {}
    normalized: dict[str, dict[str, bool]] = {}
    for query in queries:
        route = route_map.get(query) if isinstance(route_map.get(query), dict) else {}
        use_academic = bool(route.get("use_academic", True))
        use_web = bool(route.get("use_web", False))
        if not use_academic and not use_web:
            use_academic = True
        normalized[query] = {"use_academic": use_academic, "use_web": use_web}
    return normalized


def _artifact(ctx: SkillContext, artifact_type: str, payload: dict):
    return make_artifact(
        node_id=ctx.node_id,
        artifact_type=artifact_type,
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload=payload,
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
