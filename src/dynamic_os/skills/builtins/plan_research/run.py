from __future__ import annotations

import json
import re

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


SEARCH_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "brief": {"type": "string"},
        "research_questions": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 5,
        },
        "search_queries": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 6,
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
    },
    "required": ["topic", "brief", "research_questions", "search_queries", "query_routes"],
    "additionalProperties": False,
}

_EN_META_PHRASES = (
    "please",
    "help me",
    "generate",
    "create",
    "write",
    "draft",
    "plan",
    "report",
    "research loop",
    "research plan",
    "minimum",
    "topic",
    "search for",
    "find papers",
    "analyze",
    "analyse",
    "summarize",
    "summary",
    "compare",
    "review",
)
_ZH_META_PHRASES = (
    "请",
    "帮我",
    "给我",
    "生成",
    "写",
    "撰写",
    "制定",
    "规划",
    "最小研究闭环",
    "研究闭环",
    "研究计划",
    "主题",
    "报告",
    "分析",
    "比较",
    "评审",
    "审稿",
    "查找",
    "检索",
    "搜索",
    "论文",
)
_ZH_FILLER_CHUNKS = {"为一个", "一个", "一份", "关于", "有关", "针对", "围绕", "主题"}
_EN_STOPWORDS = {
    "a",
    "an",
    "the",
    "for",
    "to",
    "of",
    "and",
    "or",
    "with",
    "about",
    "on",
    "into",
    "from",
    "using",
    "use",
    "task",
    "request",
    "topic",
    "report",
    "plan",
    "research",
    "generate",
    "write",
    "draft",
    "search",
    "find",
    "paper",
    "papers",
}
_GENERIC_CJK_TOPICS = {
    "方法",
    "证据",
    "方法与证据",
    "综述",
    "评测",
    "评估",
    "研究",
    "主题",
    "报告",
}
_GENERIC_EN_TOPICS = {
    "methods",
    "evidence",
    "methods and evidence",
    "survey",
    "evaluation",
    "research",
    "topic",
    "report",
}
_GENERIC_CJK_QUERY_MARKERS = (
    "综述",
    "方法",
    "评测",
    "评估",
    "证据",
    "问题",
    "挑战",
    "架构",
    "方法与证据",
    "是什么",
    "有哪些",
    "如何",
)
_GENERIC_EN_QUERY_MARKERS = (
    "survey",
    "methods",
    "evaluation",
    "evidence",
    "challenges",
    "architecture",
    "what is",
    "what are",
    "how to",
)


async def run(ctx: SkillContext) -> SkillOutput:
    raw_plan = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": (
                    "Return JSON only. Convert the goal into a research topic brief and a search plan. "
                    "The topic must be a concise subject phrase, not a task instruction. "
                    "search_queries must be keyword-centric search strings, not imperative requests. "
                    "Prefer 3 to 5 search queries. Use academic search by default and enable web only when the query is about tools, code, products, or implementations."
                ),
            },
            {"role": "user", "content": ctx.goal},
        ],
        temperature=0.2,
        response_format=SEARCH_PLAN_SCHEMA,
    )
    parsed = _parse_structured_plan(raw_plan)
    topic = _derive_topic(goal=ctx.goal, parsed_topic=str(parsed.get("topic") or ""))
    brief = _normalize_text(str(parsed.get("brief") or "")) or _fallback_brief(goal=ctx.goal, topic=topic)
    research_questions = _normalize_questions(parsed.get("research_questions"), topic=topic, goal=ctx.goal)
    search_queries = _normalize_search_queries(
        parsed_queries=parsed.get("search_queries"),
        topic=topic,
        research_questions=research_questions,
        goal=ctx.goal,
    )
    query_routes = _normalize_query_routes(parsed.get("query_routes"), search_queries)

    topic_brief = _artifact(
        ctx,
        "TopicBrief",
        {
            "topic": topic,
            "brief": brief,
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
            "plan_text": brief,
        },
    )
    return SkillOutput(
        success=True,
        output_artifacts=[topic_brief, search_plan],
        metadata={"query_count": len(search_queries), "topic": topic},
    )


def _parse_structured_plan(raw_plan: str) -> dict:
    text = str(raw_plan or "").strip()
    fenced_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced_match:
        text = fenced_match.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _derive_topic(*, goal: str, parsed_topic: str) -> str:
    goal_topic = _extract_topic_from_goal(goal)
    for candidate in (parsed_topic, goal_topic, _keywordize_text(goal)):
        normalized = _normalize_text(candidate)
        if normalized and not _looks_like_instruction(normalized):
            if _is_generic_topic(normalized) and goal_topic and normalized != goal_topic:
                continue
            return normalized
    return _normalize_text(goal)


def _extract_topic_from_goal(goal: str) -> str:
    text = _normalize_text(goal)
    if not text:
        return ""
    for marker in ("关于", "有关", "针对", "围绕"):
        if marker in text:
            candidate = text.split(marker, 1)[1]
            candidate = _trim_topic_tail(candidate)
            candidate = _normalize_topic_candidate(candidate)
            if candidate:
                return candidate

    english_patterns = (
        r"(?:about|on|regarding)\s+(?P<topic>.+?)(?:\s+(?:for|with|to)\b|$)",
    )
    for pattern in english_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            topic = _normalize_topic_candidate(match.group("topic"))
            if topic:
                return topic
    return ""


def _normalize_questions(raw_questions: object, *, topic: str, goal: str) -> list[str]:
    questions = [_normalize_text(str(item)) for item in list(raw_questions or []) if _normalize_text(str(item))]
    deduped: list[str] = []
    for question in questions:
        if question not in deduped and not _looks_like_instruction(question):
            deduped.append(question)
    if deduped:
        return deduped[:4]
    return [_fallback_question(topic=topic, goal=goal)]


def _normalize_search_queries(
    *,
    parsed_queries: object,
    topic: str,
    research_questions: list[str],
    goal: str,
) -> list[str]:
    deduped: list[str] = []
    for item in list(parsed_queries or []):
        normalized = _normalize_query(str(item), topic=topic)
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    if deduped:
        return deduped[:5]

    fallback_queries = _fallback_queries(topic=topic, research_questions=research_questions, goal=goal)
    for query in fallback_queries:
        normalized = _normalize_query(query, topic=topic)
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped[:5] or [topic]


def _normalize_query_routes(raw_routes: object, queries: list[str]) -> dict[str, dict[str, bool]]:
    route_map = raw_routes if isinstance(raw_routes, dict) else {}
    normalized: dict[str, dict[str, bool]] = {}
    for query in queries:
        route = route_map.get(query) if isinstance(route_map.get(query), dict) else {}
        use_academic = bool(route.get("use_academic", True))
        use_web = bool(route.get("use_web", _query_prefers_web(query)))
        if not use_academic and not use_web:
            use_academic = True
        normalized[query] = {
            "use_academic": use_academic,
            "use_web": use_web,
        }
    return normalized


def _normalize_query(query: str, *, topic: str) -> str:
    text = _normalize_text(query)
    if not text:
        return ""
    if _looks_like_instruction(text):
        text = _extract_topic_from_goal(text) or _keywordize_text(text)
    text = _normalize_text(text)
    if not text:
        return ""
    if topic and _query_needs_topic(text, topic):
        text = f"{topic} {text}"
    if not _contains_cjk(text) and len(text.split()) > 10:
        text = topic
    return text


def _fallback_queries(*, topic: str, research_questions: list[str], goal: str) -> list[str]:
    base = topic or _extract_topic_from_goal(goal) or _keywordize_text(goal) or _normalize_text(goal)
    queries: list[str] = [base]
    question_seed = _keywordize_text(research_questions[0]) if research_questions else ""
    if question_seed and question_seed != base:
        queries.append(question_seed)
    if _contains_cjk(base):
        queries.extend([f"{base} 综述", f"{base} 方法", f"{base} 评测"])
    else:
        queries.extend([f"{base} survey", f"{base} methods", f"{base} evaluation"])
    deduped: list[str] = []
    for query in queries:
        normalized = _normalize_text(query)
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _fallback_question(*, topic: str, goal: str) -> str:
    if _contains_cjk(topic or goal):
        return f"{topic or _normalize_text(goal)}的核心问题、方法与证据是什么？"
    return f"What are the core problems, methods, and evidence for {topic or _normalize_text(goal)}?"


def _fallback_brief(*, goal: str, topic: str) -> str:
    if _contains_cjk(topic or goal):
        return f"研究主题：{topic}。目标是围绕该主题生成可执行的检索问题与关键词查询，而不是直接复述任务指令。"
    return f"Research topic: {topic}. The goal is to derive executable search questions and keyword-oriented queries instead of reusing the task instruction verbatim."


def _keywordize_text(text: str) -> str:
    normalized = _normalize_text(text)
    extracted_topic = _extract_topic_from_goal(normalized)
    if extracted_topic:
        return extracted_topic
    lowered = normalized.lower()
    for phrase in _EN_META_PHRASES:
        lowered = lowered.replace(phrase, " ")
    cleaned = lowered
    for phrase in _ZH_META_PHRASES:
        cleaned = cleaned.replace(phrase, " ")
    cleaned = re.sub(r"[^\w\u4e00-\u9fff\-\+/ ]+", " ", cleaned)
    english_tokens = [token for token in re.findall(r"[a-z0-9][a-z0-9_\-+/]*", cleaned) if token not in _EN_STOPWORDS]
    cjk_chunks = [_normalize_topic_candidate(chunk) for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", cleaned)]
    cjk_chunks = [chunk for chunk in cjk_chunks if chunk and chunk not in _ZH_FILLER_CHUNKS]
    if cjk_chunks:
        longest = max(cjk_chunks, key=len)
        if longest:
            return longest
    return _normalize_text(" ".join(english_tokens[:8]))


def _looks_like_instruction(text: str) -> bool:
    lowered = text.lower()
    if any(phrase in lowered for phrase in _EN_META_PHRASES):
        return True
    return any(phrase in text for phrase in _ZH_META_PHRASES)


def _is_generic_topic(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    lowered = normalized.lower()
    if lowered in _GENERIC_EN_TOPICS:
        return True
    return normalized in _GENERIC_CJK_TOPICS


def _query_needs_topic(query: str, topic: str) -> bool:
    normalized_query = _normalize_text(query)
    normalized_topic = _normalize_text(topic)
    if not normalized_query or not normalized_topic:
        return False
    lowered_query = normalized_query.lower()
    lowered_topic = normalized_topic.lower()
    if lowered_topic in lowered_query or normalized_topic in normalized_query:
        return False
    if _contains_cjk(normalized_query):
        return len(normalized_query) <= 8 or any(marker in normalized_query for marker in _GENERIC_CJK_QUERY_MARKERS)
    return len(normalized_query.split()) <= 4 or any(marker in lowered_query for marker in _GENERIC_EN_QUERY_MARKERS)


def _query_prefers_web(query: str) -> bool:
    lowered = query.lower()
    web_markers = ("github", "repo", "repository", "implementation", "open source", "tool", "framework", "代码", "开源", "工具", "框架")
    return any(marker in lowered or marker in query for marker in web_markers)


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _normalize_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    return normalized.strip(" \t\r\n\"'`.,;:!?()[]{}<>，。；：！？（）【】")


def _trim_topic_tail(text: str) -> str:
    candidate = str(text or "")
    tail_markers = (
        "的主题",
        "主题",
        "的研究",
        "研究闭环",
        "闭环",
        "研究计划",
        "报告",
        "综述",
        "生成",
        "撰写",
        "写",
        "总结",
        "分析",
        "比较",
        "评审",
        "构建",
        "设计",
        "查找",
        "检索",
        "搜索",
    )
    cut_index = len(candidate)
    for marker in tail_markers:
        marker_index = candidate.find(marker)
        if marker_index != -1:
            cut_index = min(cut_index, marker_index)
    return candidate[:cut_index]


def _normalize_topic_candidate(text: str) -> str:
    candidate = _normalize_text(text)
    candidate = re.sub(r"^(?:为一个|为|一个|一份|关于|有关|针对|围绕)+", "", candidate)
    candidate = re.sub(r"(?:的|相关|方面)+$", "", candidate)
    return _normalize_text(candidate)


def _artifact(ctx: SkillContext, artifact_type: str, payload: dict):
    return make_artifact(
        node_id=ctx.node_id,
        artifact_type=artifact_type,
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload=payload,
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
