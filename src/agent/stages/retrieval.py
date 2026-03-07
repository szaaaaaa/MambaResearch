"""Retrieval stage implementation."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List

from src.agent.core.config import (
    DEFAULT_MIN_ANCHOR_HITS,
    DEFAULT_MIN_KEYWORD_HITS,
    DEFAULT_TOPIC_BLOCK_TERMS,
)
from src.agent.core.executor import TaskRequest
from src.agent.core.schemas import ResearchState
from src.agent.core.source_ranking import _is_topic_relevant as _default_is_topic_relevant
from src.agent.core.state_access import to_namespaced_update, with_flattened_legacy_view
from src.agent.core.topic_filter import (
    _build_topic_anchor_terms as _default_build_topic_anchor_terms,
    _build_topic_keywords as _default_build_topic_keywords,
)
from src.agent.core.executor_router import dispatch as _default_dispatch

logger = logging.getLogger(__name__)


def fetch_sources(
    state: ResearchState,
    *,
    state_view: Callable[[ResearchState], Dict[str, Any]] | None = None,
    get_cfg: Callable[[ResearchState], Dict[str, Any]] | None = None,
    ns: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
    dispatch: Callable[..., Any] | None = None,
    build_topic_keywords: Callable[[ResearchState, Dict[str, Any]], set[str]] | None = None,
    build_topic_anchor_terms: Callable[[ResearchState, Dict[str, Any]], set[str]] | None = None,
    is_topic_relevant: Callable[..., bool] | None = None,
) -> Dict[str, Any]:
    """Fetch sources, apply routing, and accumulate deduplicated results."""
    state_view = state_view or with_flattened_legacy_view
    get_cfg = get_cfg or (lambda current_state: current_state.get("_cfg", {}))
    ns = ns or to_namespaced_update
    dispatch = dispatch or _default_dispatch
    build_topic_keywords = build_topic_keywords or _default_build_topic_keywords
    build_topic_anchor_terms = build_topic_anchor_terms or _default_build_topic_anchor_terms
    is_topic_relevant = is_topic_relevant or _default_is_topic_relevant

    state = state_view(state)
    cfg = get_cfg(state)
    root = Path(cfg.get("_root", "."))

    academic_queries = state.get("_academic_queries", state.get("search_queries", []))
    web_queries = state.get("_web_queries", state.get("search_queries", []))
    query_routes = state.get("query_routes", {})

    effective_academic_queries = [
        query for query in academic_queries if query_routes.get(query, {}).get("use_academic", True)
    ]
    effective_web_queries = list(
        dict.fromkeys(
            [query for query in web_queries if query_routes.get(query, {}).get("use_web", True)]
            + [
                query
                for query in academic_queries
                if query_routes.get(query, {}).get("use_web", False) and query not in web_queries
            ]
        )
    )

    existing_uids = {paper["uid"] for paper in state.get("papers", [])}
    existing_web_uids = {web_source["uid"] for web_source in state.get("web_sources", [])}
    topic_keywords = build_topic_keywords(state, cfg)
    topic_anchor_terms = build_topic_anchor_terms(state, cfg)
    topic_filter_cfg = cfg.get("agent", {}).get("topic_filter", {})
    block_terms = topic_filter_cfg.get("block_terms", DEFAULT_TOPIC_BLOCK_TERMS)
    min_hits = int(topic_filter_cfg.get("min_keyword_hits", DEFAULT_MIN_KEYWORD_HITS))
    min_anchor_hits = int(
        topic_filter_cfg.get(
            "min_anchor_hits",
            DEFAULT_MIN_ANCHOR_HITS if topic_anchor_terms else 0,
        )
    )

    existing_papers: List[Dict[str, Any]] = list(state.get("papers", []))
    existing_web: List[Dict[str, Any]] = list(state.get("web_sources", []))
    new_papers: List[Dict[str, Any]] = []
    new_web: List[Dict[str, Any]] = []

    search_result = dispatch(
        TaskRequest(
            action="search",
            params={
                "root": str(root),
                "academic_queries": effective_academic_queries,
                "web_queries": effective_web_queries,
                "query_routes": query_routes,
            },
        ),
        cfg,
    )
    if not search_result.success:
        return ns(
            {
                "papers": existing_papers,
                "web_sources": existing_web,
                "status": f"Fetch failed: {search_result.error}",
            }
        )
    provider_result = search_result.data

    for paper in provider_result.get("papers", []):
        rel_text = f"{paper.get('title', '')} {paper.get('abstract', '')}"
        if not is_topic_relevant(
            text=rel_text,
            topic_keywords=topic_keywords,
            block_terms=block_terms,
            min_hits=min_hits,
            anchor_terms=topic_anchor_terms,
            min_anchor_hits=min_anchor_hits,
        ):
            logger.debug("[TopicFilter] Drop paper candidate: %s", paper.get("title", ""))
            continue
        uid = paper.get("uid")
        if not uid or uid in existing_uids:
            continue
        new_papers.append(paper)
        existing_uids.add(uid)

    for web_source in provider_result.get("web_sources", []):
        rel_text = f"{web_source.get('title', '')} {web_source.get('snippet', '')}"
        if not is_topic_relevant(
            text=rel_text,
            topic_keywords=topic_keywords,
            block_terms=block_terms,
            min_hits=min_hits,
            anchor_terms=topic_anchor_terms,
            min_anchor_hits=min_anchor_hits,
        ):
            logger.debug("[TopicFilter] Drop web candidate: %s", web_source.get("title", ""))
            continue
        uid = web_source.get("uid")
        if not uid or uid in existing_web_uids:
            continue
        new_web.append(web_source)
        existing_web_uids.add(uid)

    cumulative_papers = existing_papers + new_papers
    cumulative_web = existing_web + new_web
    return ns(
        {
            "papers": cumulative_papers,
            "web_sources": cumulative_web,
            "status": (
                f"Fetched {len(new_papers)} new papers, {len(new_web)} new web sources "
                f"(cumulative: {len(cumulative_papers)} papers, {len(cumulative_web)} web) "
                f"[routes: {len(effective_academic_queries)} academic, {len(effective_web_queries)} web]"
            ),
        }
    )
