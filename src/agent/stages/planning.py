"""Planning stage implementation."""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict

from src.agent.core.config import DEFAULT_MAX_CONTEXT_CHARS, DEFAULT_MAX_FINDINGS_FOR_CONTEXT
from src.agent.core.query_planning import (
    _academic_sources_enabled,
    _compress_findings_for_context,
    _expand_query_set,
    _load_budget_and_scope,
    _route_query,
    _web_sources_enabled,
)
from src.agent.core.schemas import ResearchState
from src.agent.core.state_access import to_namespaced_update, with_flattened_legacy_view
from src.agent.prompts import (
    PLAN_RESEARCH_REFINE_CONTEXT,
    PLAN_RESEARCH_SYSTEM,
    PLAN_RESEARCH_USER,
)
from src.agent.stages.runtime import llm_call as _runtime_llm_call, parse_json as _runtime_parse_json

logger = logging.getLogger(__name__)


def plan_research(
    state: ResearchState,
    *,
    state_view: Callable[[ResearchState], Dict[str, Any]] | None = None,
    get_cfg: Callable[[ResearchState], Dict[str, Any]] | None = None,
    load_budget_and_scope: Callable[[ResearchState, Dict[str, Any]], tuple[Dict[str, Any], Dict[str, int]]] | None = None,
    ns: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
    llm_call: Callable[..., str] | None = None,
    parse_json: Callable[[str], Dict[str, Any]] | None = None,
    compress_findings_for_context: Callable[..., str] | None = None,
    expand_query_set: Callable[..., list[Dict[str, str]]] | None = None,
    academic_sources_enabled: Callable[[Dict[str, Any]], bool] | None = None,
    web_sources_enabled: Callable[[Dict[str, Any]], bool] | None = None,
    route_query: Callable[[str, Dict[str, Any]], Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Decompose the topic into research questions and routed search queries."""
    state_view = state_view or with_flattened_legacy_view
    get_cfg = get_cfg or (lambda current_state: current_state.get("_cfg", {}))
    load_budget_and_scope = load_budget_and_scope or _load_budget_and_scope
    ns = ns or to_namespaced_update
    llm_call = llm_call or _runtime_llm_call
    parse_json = parse_json or _runtime_parse_json
    compress_findings_for_context = compress_findings_for_context or _compress_findings_for_context
    expand_query_set = expand_query_set or _expand_query_set
    academic_sources_enabled = academic_sources_enabled or _academic_sources_enabled
    web_sources_enabled = web_sources_enabled or _web_sources_enabled
    route_query = route_query or _route_query

    state = state_view(state)
    topic = state["topic"]
    iteration = state.get("iteration", 0)
    cfg = get_cfg(state)
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.3)
    scope, budget = load_budget_and_scope(state, cfg)

    context = ""
    prev_findings = ""
    if iteration > 0:
        mem_cfg = cfg.get("agent", {}).get("memory", {})
        prev_findings = compress_findings_for_context(
            state.get("findings", []),
            max_items=int(mem_cfg.get("max_findings_for_context", DEFAULT_MAX_FINDINGS_FOR_CONTEXT)),
            max_chars=int(mem_cfg.get("max_context_chars", DEFAULT_MAX_CONTEXT_CHARS)),
        )
        prev_gaps = "\n".join(f"- {gap}" for gap in state.get("gaps", []))
        prev_queries = ", ".join(state.get("search_queries", []))
        context = PLAN_RESEARCH_REFINE_CONTEXT.format(
            findings=prev_findings or "(none yet)",
            gaps=prev_gaps or "(none yet)",
            previous_queries=prev_queries or "(none)",
        )

    prompt = PLAN_RESEARCH_USER.format(
        topic=topic,
        context=context
        + (
            f"\n\nScope intent: {scope.get('intent')}\n"
            f"Allowed sections: {', '.join(scope.get('allowed_sections', []))}\n"
            f"Budget limits: RQ <= {budget['max_research_questions']}, "
            f"Sections <= {budget['max_sections']}, References <= {budget['max_references']}\n\n"
        ),
    )

    raw = llm_call(PLAN_RESEARCH_SYSTEM, prompt, cfg=cfg, model=model, temperature=temperature)

    try:
        result = parse_json(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse plan_research JSON, using fallback")
        result = {
            "research_questions": [f"What are the key developments in {topic}?"],
            "academic_queries": [topic],
            "web_queries": [topic],
        }

    max_q = int(cfg.get("agent", {}).get("max_queries_per_iteration", 3))
    seed_academic_queries = result.get("academic_queries", result.get("search_queries", [topic]))[:max_q]
    seed_web_queries = result.get("web_queries", [topic])[:max_q]
    research_questions = result.get("research_questions", [])[: max(1, budget["max_research_questions"])]
    if not research_questions:
        research_questions = [f"What are the key developments in {topic}?"]

    focus_rqs = state.get("_focus_research_questions", [])
    rewrite_targets = (
        [rq for rq in research_questions if rq in focus_rqs]
        if isinstance(focus_rqs, list) and focus_rqs
        else research_questions
    )
    if not rewrite_targets:
        rewrite_targets = research_questions

    rewrite_cfg = cfg.get("agent", {}).get("query_rewrite", {})
    min_per_rq = int(rewrite_cfg.get("min_per_rq", 6))
    max_per_rq = int(rewrite_cfg.get("max_per_rq", 8))
    per_rq = max(min_per_rq, min(10, max_per_rq))
    max_total_queries = int(
        rewrite_cfg.get(
            "max_total_queries",
            max(max_q, len(rewrite_targets) * per_rq),
        )
    )
    expanded_queries = expand_query_set(
        topic=topic,
        rq_list=rewrite_targets,
        seed_queries=list(dict.fromkeys(seed_academic_queries + seed_web_queries)),
        max_per_rq=per_rq,
        max_total=max_total_queries,
    )
    if not expanded_queries:
        expanded_queries = [{"query": topic, "type": "precision"}]

    query_type_map = {item["query"]: item["type"] for item in expanded_queries}
    precision_queries = [item["query"] for item in expanded_queries if item["type"] == "precision"]
    recall_queries = [item["query"] for item in expanded_queries if item["type"] == "recall"]

    academic_queries = list(dict.fromkeys([item["query"] for item in expanded_queries]))
    web_queries = list(dict.fromkeys(recall_queries + seed_web_queries))

    if not academic_sources_enabled(cfg):
        academic_queries = []
    if not web_sources_enabled(cfg):
        web_queries = []

    all_queries = list(dict.fromkeys(academic_queries + web_queries))
    query_routes = {}
    for query in all_queries:
        route = route_query(query, cfg)
        route["query_type"] = query_type_map.get(query, "precision")
        query_routes[query] = route

    routed_academic = [
        query for query in academic_queries if query_routes.get(query, {}).get("use_academic", True)
    ]
    routed_web = list(
        dict.fromkeys(
            web_queries
            + [
                query
                for query in academic_queries
                if query_routes.get(query, {}).get("use_web", False) and query not in web_queries
            ]
        )
    )

    return ns(
        {
            "research_questions": research_questions,
            "search_queries": all_queries,
            "scope": scope,
            "budget": budget,
            "query_routes": query_routes,
            "memory_summary": prev_findings if iteration > 0 else "",
            "_academic_queries": routed_academic,
            "_web_queries": routed_web,
            "_focus_research_questions": [],
            "status": (
                f"Iteration {iteration}: planned {len(routed_academic)} academic + "
                f"{len(routed_web)} web queries under scoped budget "
                f"[enabled: academic={academic_sources_enabled(cfg)}, web={web_sources_enabled(cfg)}, "
                f"precision={len(precision_queries)}, recall={len(recall_queries)}]"
            ),
        }
    )
